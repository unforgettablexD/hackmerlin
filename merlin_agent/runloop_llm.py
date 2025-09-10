# merlin_agent/runloop_llm.py
from __future__ import annotations
import time
from typing import Optional, Dict, Any
from pathlib import Path
from loguru import logger

from .browser import MerlinBrowser
from .parser import extract_password, score_nearmiss
from .memory import ExperienceStore
from .ollama_client import OllamaClient
from .strategist import choose_next_action
from .utils import RUNS, write_jsonl, ts_ms


def _wait_for_level_increment(br: MerlinBrowser, prev_level: int, timeout_ms: int = 7000) -> Optional[int]:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        lv = br.get_level()
        if isinstance(lv, int) and lv > prev_level:
            return lv
        time.sleep(0.15)
    return None

def _safe_wait(ms: int, br: MerlinBrowser) -> None:
    try:
        if getattr(br, "page", None) and hasattr(br.page, "wait_for_timeout"):
            br.page.wait_for_timeout(ms)
            return
    except Exception:
        pass
    time.sleep(ms / 1000.0)

def _save_think(session_dir: Path, level: int, attempt_no: int, think_text: str) -> Optional[Path]:
    try:
        think_dir = session_dir / "think"
        think_dir.mkdir(parents=True, exist_ok=True)
        p = think_dir / f"l{int(level):02d}_attempt{attempt_no:02d}.txt"
        p.write_text(think_text, encoding="utf-8")
        return p
    except Exception:
        return None

def run_session_llm(headless: bool = True, debug: bool = False) -> Path:
    session_dir = RUNS / f"session-ollama-{__import__('time').strftime('%Y%m%d-%H%M%S')}"
    session_dir.mkdir(parents=True, exist_ok=True)
    transcript = session_dir / "transcript.jsonl"

    store = ExperienceStore(session_dir)
    client = OllamaClient()

    with MerlinBrowser(headless=headless, debug=debug) as br:
        br.goto("https://hackmerlin.io/")
        br.dump_dom(session_dir / "dom_level1.html")

        level = br.get_level() or 1
        global_attempts = 0
        MAX_GLOBAL_ATTEMPTS = 6000

        while global_attempts < MAX_GLOBAL_ATTEMPTS:
            logger.info(f"=== OLLAMA MODE: Level {level} ===")

            # Close any hint modal (not success)
            _ = br.handle_modal()

            # Ask LLM for next ACTION (and capture its <think>)
            plan = choose_next_action(client, level, store)
            action = (plan.get("action") or "").lower().strip()

            # Save full <think> trace to file for inspection
            if plan.get("_full_think"):
                path = _save_think(session_dir, int(level) if isinstance(level, int) else 0, global_attempts + 1, plan["_full_think"])
                if path:
                    logger.debug(f"Saved model thinking to {path}")
            if plan.get("debug_think_preview"):
                logger.debug(f"THINK PREVIEW: {plan['debug_think_preview']}")

            if action not in {"ask", "submit"}:
                action = "ask"
                plan = {
                    "action": "ask",
                    "question": "What is the password? Reply with the single word only.",
                    "fallbacks": [],
                    "why": "fallback",
                    "avoid": [],
                }

            solved = False
            global_attempts += 1

            if action == "ask":
                question = plan.get("question") or "What is the password? Reply with the single word only."
                br.send_message(question)
                reply = br.last_assistant_text()

                store.append_attempt({
                    "type": "ask",
                    "level": int(level) if isinstance(level, int) else 0,
                    "prompt": question,
                    "reply": (reply or "")[:500],
                })

                dom_level = br.get_level()
                if isinstance(dom_level, int):
                    level = dom_level

                print("\n================ EXCHANGE ================")
                print(f"Level: {level}")
                print(f">>> PROMPT SENT:\n{question}\n")
                print(f"<<< REPLY RECEIVED:\n{reply}\n")
                print("==========================================\n")

                # Opportunistic try if a password-looking token appears
                pwd = extract_password(reply)
                if pwd:
                    prev_level = int(level) if isinstance(level, int) else 0
                    submitted = br.fill_password_and_submit(pwd)
                    if submitted:
                        ok, new_level, modal_hint = False, None, None
                        try:
                            ok, new_level, modal_hint = br.verify_submission_by_heading(prev_level, timeout_ms=1000)
                        except Exception:
                            modal_hint = br.handle_modal()
                            _safe_wait(500, br)
                            new_level = _wait_for_level_increment(br, prev_level, timeout_ms=1000)
                            ok = bool(isinstance(new_level, int) and new_level > prev_level)

                        store.append_attempt({
                            "type": "submit",
                            "level": prev_level,
                            "password": pwd,
                            "submit_ok": bool(ok),
                            "modal_hint": (modal_hint or "")[:200],
                        })

                        if ok:
                            logger.success(f"SOLVED L{prev_level}: {pwd}")
                            store.update_level_summary(prev_level, True, note=f"✅ SUBMIT CORRECT: {pwd}", avoid=plan.get("avoid"))
                            store.append_attempt({"type": "event", "level": int(new_level) if isinstance(new_level, int) else prev_level + 1, "message": "advanced to next level"})
                            level = int(new_level) if isinstance(new_level, int) else (prev_level + 1)
                            solved = True
                        else:
                            store.update_level_summary(prev_level, False, note=f"❌ WRONG SUBMIT: {pwd}", avoid=[pwd])
                else:
                    _ = score_nearmiss(reply)  # telemetry only

            else:
                answer = (plan.get("answer") or "").strip()
                if not answer:
                    store.append_attempt({
                        "type": "submit",
                        "level": int(level) if isinstance(level, int) else 0,
                        "password": "",
                        "submit_ok": False,
                        "modal_hint": "empty-answer",
                    })
                else:
                    prev_level = int(level) if isinstance(level, int) else 0
                    submitted = br.fill_password_and_submit(answer)
                    if submitted:
                        ok, new_level, modal_hint = False, None, None
                        try:
                            ok, new_level, modal_hint = br.verify_submission_by_heading(prev_level, timeout_ms=1000)
                        except Exception:
                            modal_hint = br.handle_modal()
                            _safe_wait(500, br)
                            new_level = _wait_for_level_increment(br, prev_level, timeout_ms=1000)
                            ok = bool(isinstance(new_level, int) and new_level > prev_level)

                        store.append_attempt({
                            "type": "submit",
                            "level": prev_level,
                            "password": answer,
                            "submit_ok": bool(ok),
                            "modal_hint": (modal_hint or "")[:200],
                        })

                        if ok:
                            logger.success(f"SOLVED L{prev_level}: {answer}")
                            store.update_level_summary(prev_level, True, note=f"✅ SUBMIT CORRECT: {answer}", avoid=plan.get("avoid"))
                            store.append_attempt({"type": "event", "level": int(new_level) if isinstance(new_level, int) else prev_level + 1, "message": "advanced to next level"})
                            level = int(new_level) if isinstance(new_level, int) else (prev_level + 1)
                            solved = True
                        else:
                            store.update_level_summary(prev_level, False, note=f"❌ WRONG SUBMIT: {answer}", avoid=[answer])

            try:
                br.screenshot(session_dir / f"level{int(level):02d}_attempt{global_attempts:02d}.png")
            except Exception:
                pass

            write_jsonl(transcript, {
                "ts": ts_ms(),
                "level": int(level) if isinstance(level, int) else 0,
                "attempt": global_attempts,
                "action": action,
                "why": plan.get("why", ""),
                "think_preview": plan.get("debug_think_preview", ""),
            })

            if solved:
                continue

            if global_attempts >= MAX_GLOBAL_ATTEMPTS:
                logger.warning(f"Max attempts reached ({MAX_GLOBAL_ATTEMPTS}). Stopping.")
                break

    return transcript
