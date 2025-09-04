from __future__ import annotations
from typing import Optional
from .ollama_client import OllamaClient

def llm_extract_password(client: OllamaClient, reply: str) -> Optional[str]:
    if not reply:
        return None
    try:
        obj = client.extract_password(reply)
        pw = obj.get("password")
        if isinstance(pw, str) and pw.strip():
            return pw.strip().upper()
        return None
    except Exception:
        return None
