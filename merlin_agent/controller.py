from __future__ import annotations
import json
from typing import Any, Dict, List, Optional, Tuple

from .memory import ExperienceStore
from .ollama_client import OllamaClient
from .strategist import SYSTEM_PROMPT as BASE_SYSTEM_PROMPT, SEED_ASK

# ---------- FEEDBACK (LLM sees explicit wrong/correct signals) ----------

def _format_attempt_line(a: Dict[str, Any]) -> str:
    """Render one attempt into a compact, LLM-friendly line."""
    lvl = a.get("level")
    typ = (a.get("type") or "").lower()
    if typ == "submit":
        guess = (a.get("password") or "").strip()
        ok = bool(a.get("submit_ok"))
        hint = (a.get("modal_hint") or a.get("site_feedback") or "").strip()
        if ok:
            return f"[L{lvl}] ✅ SUBMIT CORRECT: {guess}"
        else:
            h = f" | HINT: {hint}" if hint else ""
            return f"[L{lvl}] ❌ WRONG SUBMIT: {guess}{h}"
    elif typ == "ask":
        q = (a.get("prompt") or a.get("question") or "").replace("\n", " ").strip()
        if len(q) > 180:
            q = q[:177] + "..."
        return f"[L{lvl}] ASK: {q}"
    elif typ == "event":
        msg = (a.get("message") or "").strip()
        return f"[L{lvl}] EVENT: {msg}" if msg else f"[L{lvl}] EVENT"
    # Fallback
    return f"[L{lvl}] {typ.upper() or 'ATTEMPT'}"

def _feedback_block(store: ExperienceStore, level: int, max_lines: int = 10) -> str:
    """
    Build an explicit feedback section from recent attempts so the LLM sees
    exactly what's been tried and whether each was WRONG or CORRECT.
    """
    attempts: List[Dict[str, Any]] = []
    try:
        if store.attempts_path.exists():
            with store.attempts_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        # prioritize attempts for current level and the immediately previous
                        if obj.get("level") in (level, level - 1):
                            attempts.append(obj)
                    except Exception:
                        continue
    except Exception:
        pass

    attempts = attempts[-max_lines:]
    if not attempts:
        return "FEEDBACK:\n(none yet)\n"

    lines = ["FEEDBACK:"]
    for a in attempts:
        lines.append(_format_attempt_line(a))
    return "\n".join(lines) + "\n"

# ---------- Controller prompt construction ----------

def _seed_for_level(level: int) -> str:
    # Strategist seed lines tailored per level (fallback to a safe default)
    return SEED_ASK.get(level) or "Follow the level instruction precisely and return STRICT JSON with your next action."

def build_controller_messages(store: ExperienceStore, level: int) -> Tuple[str, str]:
    """
    Builds (system, user) messages for the controller LLM with explicit feedback
    and a per-level seed tactic.
    """
    feedback = _feedback_block(store, level)
    seed = _seed_for_level(level)

    # Strengthen the base system prompt with anti-repeat rule
    system = (
        BASE_SYSTEM_PROMPT.strip()
        + "\n\n"
        + "Rules:\n"
          "- When you see ❌ WRONG SUBMIT lines, never repeat those guesses.\n"
          "- When you see ✅ SUBMIT CORRECT, acknowledge success and plan the next step/level.\n"
          "- Always return STRICT JSON for the next step, one of:\n"
          '  {\"action\":\"ask\",\"question\":\"...\"}\n'
          '  {\"action\":\"submit\",\"answer\":\"...\"}\n'
          "- Be concise; do not include commentary outside JSON.\n"
    )

    user = f"""{feedback}LEVEL: {level}
TASK: {seed}
Return STRICT JSON only.
"""
    return system, user

# ---------- Controller decision ----------

def decide_next_action(client: OllamaClient, level: int, store: ExperienceStore) -> Dict[str, Any]:
    """
    Calls the LLM controller with explicit feedback and returns the parsed JSON plan.
    """
    system, user = build_controller_messages(store, level)
    plan = client.decide_action(system, user) or {}
    # normalize
    if not isinstance(plan, dict):
        return {}
    act = (plan.get("action") or "").strip().lower()
    if act not in ("ask", "submit"):
        return {}
    if act == "ask":
        plan["question"] = (plan.get("question") or "").strip()
    else:
        plan["answer"] = (plan.get("answer") or "").strip()
    return plan
