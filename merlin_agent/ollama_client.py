from __future__ import annotations
import os, json, re
import requests
from typing import Dict, Any, Optional, Tuple

def _coerce_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        start = text.find("{"); end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
    except Exception:
        pass
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return {"primary": {"prompt": text, "why": "fallback-raw"}, "fallbacks": [], "avoid": []}

class OllamaClient:
    """
    Minimal client for ollama /api/chat.
    Hard-defaults to deepseek-r1:7b @ http://localhost:11434
    """
    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or os.environ.get("OLLAMA_MODEL", "deepseek-r1:7b")
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.endpoint = f"{self.base_url}/api/chat"
        self.tags_endpoint = f"{self.base_url}/api/tags"

    def _ensure_server(self):
        try:
            r = requests.get(self.tags_endpoint, timeout=10)
            r.raise_for_status()
        except Exception as e:
            raise RuntimeError(
                f"Ollama not reachable at {self.base_url}. "
                f"Start it with 'ollama serve' and ensure your model is pulled "
                f"(e.g., 'ollama pull {self.model}'). Original error: {e}"
            )

    def propose_prompts(self, system: str, user: str) -> Dict[str, Any]:
        self._ensure_server()
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.7}
        }
        r = requests.post(self.endpoint, json=payload, timeout=90)
        r.raise_for_status()
        data = r.json()
        content = data.get("message", {}).get("content", "")
        parsed = _coerce_json(content)
        parsed.setdefault("fallbacks", [])
        parsed.setdefault("avoid", [])
        return parsed

    def extract_password_from_text(self, reply: str) -> Optional[str]:
        system = "Extract ONLY the single password token from the user's message. Reply as JSON: {\"password\":\"TOKEN\"}."
        user = f"Message:\n{reply}\nRules: token must be ONE WORD in UPPERCASE with no spaces."
        payload = {
            "model": self.model,
            "messages": [{"role":"system","content":system},{"role":"user","content":user}],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0}
        }
        r = requests.post(self.endpoint, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        content = data.get("message", {}).get("content", "")
        try:
            obj = json.loads(content)
            tok = obj.get("password")
            if isinstance(tok, str) and tok.strip() and " " not in tok:
                return tok.strip().rstrip(".,;:!?")
        except Exception:
            pass
        return None
