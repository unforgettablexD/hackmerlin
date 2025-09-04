from __future__ import annotations
import json, pathlib
from typing import Any, Dict, List

class ExperienceStore:
    def __init__(self, session_dir: pathlib.Path):
        self.session_dir = session_dir
        self.attempts_path = session_dir / "attempts.jsonl"
        self.summary_path = session_dir / "level_summaries.json"
        self.summary: Dict[str, Any] = {}
        if self.summary_path.exists():
            self.summary = json.loads(self.summary_path.read_text(encoding="utf-8"))

    def append_attempt(self, obj: Dict[str, Any]) -> None:
        with self.attempts_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def get_recent_attempts(self, level: int, k: int = 5) -> List[Dict[str, Any]]:
        if not self.attempts_path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        with self.attempts_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec.get("level") == level:
                        rows.append(rec)
                except Exception:
                    pass
        return rows[-k:]

    def load_level_summary(self, level: int) -> Dict[str, Any]:
        return self.summary.get(str(level), {
            "tried": 0, "successes": 0, "last_k_patterns": [], "do_not_try": [], "suggested_next": None
        })

    def update_level_summary(self, level: int, success: bool, note: str = "", avoid: list | None = None):
        L = str(level)
        s = self.summary.get(L, {
            "tried": 0, "successes": 0, "last_k_patterns": [], "do_not_try": [], "suggested_next": None
        })
        s["tried"] += 1
        if success:
            s["successes"] += 1
        if note:
            s["last_k_patterns"] = (s.get("last_k_patterns", []) + [note])[-6:]
        if avoid:
            # de-dup
            s["do_not_try"] = list({*s.get("do_not_try", []), *avoid})
        self.summary[L] = s
        self.summary_path.write_text(json.dumps(self.summary, ensure_ascii=False, indent=2), encoding="utf-8")
