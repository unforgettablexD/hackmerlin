from __future__ import annotations
import json, time, re
from pathlib import Path
from typing import Any, Dict
from loguru import logger

# Project root (package folder's parent)
ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
RUNS.mkdir(parents=True, exist_ok=True)

def ts_ms() -> int:
    return int(time.time() * 1000)

def write_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def strip_markdown(text: str) -> str:
    return re.sub(r"`{1,3}", "", text or "")

def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
