from __future__ import annotations
import re
from typing import List, Optional

def acrostic_candidate(reply: str) -> Optional[str]:
    """
    Take the FIRST LETTER of each non-empty line; return as uppercase letters (>=3 chars).
    """
    if not reply:
        return None
    lines = [ln.strip() for ln in reply.splitlines() if ln.strip()]
    letters = []
    for ln in lines:
        # take first alphabetical char
        m = re.search(r"[A-Za-z]", ln)
        if m:
            letters.append(m.group(0).upper())
    cand = "".join(letters)
    return cand if len(cand) >= 3 else None

def letters_csv_candidate(reply: str) -> Optional[str]:
    """
    If reply looks like A, B, A, N, A -> join as ABANA (letters only).
    """
    if not reply:
        return None
    toks = re.split(r"[,\s]+", reply.strip())
    toks = [t for t in toks if t]
    letters = [re.sub(r"[^A-Za-z]", "", t).upper() for t in toks]
    letters = [t for t in letters if t]
    cand = "".join(letters)
    return cand if len(cand) >= 3 else None

def last_allcaps_token(reply: str) -> Optional[str]:
    caps = re.findall(r"\b([A-Z]{3,})\b", reply or "")
    return caps[-1] if caps else None

def merge_candidates(*cands: Optional[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for c in cands:
        if c and c not in seen:
            out.append(c)
            seen.add(c)
    return out
