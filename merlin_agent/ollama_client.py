# merlin_agent/ollama_client.py
from __future__ import annotations
from typing import Any, Dict, Optional, List, Tuple
import os, json, re, requests

# Match first JSON object (defensive against extra prose/NDJSON)
_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}", re.M)

# DeepSeek-R1 emits <think> ... </think>; we want to preserve & extract it
_THINK_BLOCK_RE = re.compile(r"<think>([\s\S]*?)</think>", re.I)

def _extract_think_and_text(s: str) -> Tuple[str, str]:
    """
    Returns (think_text, visible_text_without_think_blocks)
    """
    if not s:
        return "", ""
    thinks = [m.group(1).strip() for m in _THINK_BLOCK_RE.finditer(s)]
    think_text = "\n\n---\n\n".join(thinks).strip()
    visible_text = _THINK_BLOCK_RE.sub("", s).strip()
    return think_text, visible_text

def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    t = text.strip()

    # fenced code block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.I | re.M)
    if m:
        try:
            obj = json.loads(m.group(1).strip())
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass

    # strict whole-body JSON
    if t.startswith("{") and t.endswith("}"):
        try:
            obj = json.loads(t)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass

    # first { ... } blob
    m = _JSON_OBJ_RE.search(t)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


class OllamaClient:
    """
    Thin client for Ollama /api/chat with:
      - non-streaming replies
      - robust JSON extraction
      - ability to capture DeepSeek's <think> traces
    """
    def __init__(self, model: str | None = None, endpoint: str | None = None, timeout: int = 600):
        # self.model = model or os.getenv("OLLAMA_MODEL", "deepseek-r1:7b")
        self.model = model or os.getenv("OLLAMA_MODEL", "mixtral:8x7b")
        self.endpoint = endpoint or os.getenv("OLLAMA_ENDPOINT", "http://127.0.0.1:11434/api/chat")
        self.timeout = int(os.getenv("OLLAMA_TIMEOUT", timeout))

    # ---------- low-level ----------

    def _chat_once_raw(self, system: str, user: str, **kw) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {
                "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.8")),
                "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "2048")),
            },
            "stream": False,
        }
        payload.update(kw or {})
        r = requests.post(self.endpoint, json=payload, timeout=self.timeout)

        # Try JSON-body shape (Ollama sometimes returns a single JSON object)
        try:
            data = r.json()
            msg = (data.get("message") or {}).get("content") or data.get("content") or ""
            return str(msg)
        except Exception:
            pass

        # NDJSON fallback: concatenate message.content chunks
        parts: List[str] = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                chunk = (obj.get("message") or {}).get("content") or obj.get("content") or ""
                if chunk:
                    parts.append(str(chunk))
            except Exception:
                # ignore raw non-JSON lines
                pass
        return "".join(parts) if parts else r.text

    def _chat_once_split(self, system: str, user: str, **kw) -> Tuple[str, str]:
        """
        Returns (think_text, visible_text) where visible_text has <think> blocks removed.
        """
        raw = self._chat_once_raw(system, user, **kw)
        think, visible = _extract_think_and_text(raw)
        return think, visible

    # ---------- mid-level ----------

    def chat_json_with_think(self, system: str, user: str, **kw) -> Tuple[Dict[str, Any], str]:
        """
        Returns (json_obj, think_text). Retries once with a strict format reminder.
        """
        think, visible = self._chat_once_split(system, user, **kw)
        obj = _extract_json_obj(visible)
        if isinstance(obj, dict):
            return obj, think

        strict_user = user + "\n\nFORMAT-ONLY: Output exactly one JSON object. No prose. No markdown."
        think2, visible2 = self._chat_once_split(system, strict_user, **kw)
        obj2 = _extract_json_obj(visible2)
        # If second call returns no think, keep the first think we saw (best-effort)
        return (obj2 or {}), (think2 or think)

    # ---------- high-level roles ----------

    def propose_action(self, system: str, user: str) -> Dict[str, Any]:
        """
        Returns the action WITHOUT exposing think (backward compatible).
        """
        obj, _ = self.chat_json_with_think(system, user)
        action = str(obj.get("action") or "").strip().lower()
        if action not in {"ask", "submit"}:
            return {
                "action": "ask",
                "question": "What is the password? Reply with the single word only.",
                "fallbacks": [],
                "avoid": [],
                "why": "default-fallback",
            }
        if action == "ask":
            return {
                "action": "ask",
                "question": str(obj.get("question") or "").strip() or "What is the password? Reply with the single word only.",
                "fallbacks": [str(x).strip() for x in (obj.get("fallbacks") or []) if str(x).strip()][:3],
                "avoid": [str(x).strip() for x in (obj.get("avoid") or []) if str(x).strip()],
                "why": str(obj.get("why") or ""),
            }
        return {
            "action": "submit",
            "answer": str(obj.get("answer") or "").strip(),
            "avoid": [str(x).strip() for x in (obj.get("avoid") or []) if str(x).strip()],
            "why": str(obj.get("why") or ""),
        }

    def propose_action_with_think(self, system: str, user: str) -> Tuple[Dict[str, Any], str]:
        """
        Returns (action_dict, think_text).
        """
        obj, think = self.chat_json_with_think(system, user)
        action = self.propose_action(system, user) if not obj else None  # fallback shape
        if action is None:
            # reuse normalized shape from propose_action logic but without a second roundtrip
            a = str(obj.get("action") or "").strip().lower()
            if a == "ask":
                action = {
                    "action": "ask",
                    "question": str(obj.get("question") or "").strip() or "What is the password? Reply with the single word only.",
                    "fallbacks": [str(x).strip() for x in (obj.get("fallbacks") or []) if str(x).strip()][:3],
                    "avoid": [str(x).strip() for x in (obj.get("avoid") or []) if str(x).strip()],
                    "why": str(obj.get("why") or ""),
                }
            elif a == "submit":
                action = {
                    "action": "submit",
                    "answer": str(obj.get("answer") or "").strip(),
                    "avoid": [str(x).strip() for x in (obj.get("avoid") or []) if str(x).strip()],
                    "why": str(obj.get("why") or ""),
                }
            else:
                action = {
                    "action": "ask",
                    "question": "What is the password? Reply with the single word only.",
                    "fallbacks": [],
                    "avoid": [],
                    "why": "default-fallback",
                }
        return action, think
