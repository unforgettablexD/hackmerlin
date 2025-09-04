from __future__ import annotations
from pathlib import Path
from loguru import logger
from .browser import MerlinBrowser
from .parser import extract_password, score_nearmiss
from .memory import ExperienceStore
from .ollama_client import OllamaClient
from .strategist import choose_next_prompt
from .utils import RUNS, write_jsonl, ts_ms

def run_session_llm(headless: bool=True, debug: bool=False) -> Path:
    session_dir = RUNS / f"session-ollama-{__import__('time').strftime('%Y%m%d-%H%M%S')}"
    session_dir.mkdir(parents=True, exist_ok=True)
    transcript = session_dir / "transcript.jsonl"
    store = ExperienceStore(session_dir)
    client = OllamaClient()

    with MerlinBrowser(headless=headless, debug=debug) as br:
        br.goto("https://hackmerlin.io/")
        br.dump_dom(session_dir / "dom_level1.html")

        # Try to read level from DOM
        level, global_attempts = br.get_level() or 1, 0
        MAX_GLOBAL_ATTEMPTS = 60

        while global_attempts < MAX_GLOBAL_ATTEMPTS:
            logger.info(f"=== OLLAMA MODE: Level {level} ===")
            _ = br.handle_modal() 

            plan = choose_next_prompt(client, level, store)
            candidates = [plan["primary"]] + plan["fallbacks"]
            candidates = [c for c in candidates if c and c.strip()]
            if not candidates:
                logger.warning("No prompt proposed; stopping.")
                break

            solved = False
            for prompt in candidates[:3]:
                global_attempts += 1

                br.send_message(prompt)
                reply = br.last_assistant_text()

                # Re-read level in case UI changed it
                dom_level = br.get_level()
                if dom_level:
                    level = dom_level

                print("\n================ EXCHANGE ================")
                print(f"Level: {level}")
                print(f">>> PROMPT SENT:\n{prompt}\n")
                print(f"<<< REPLY RECEIVED:\n{reply}\n")
                print("==========================================\n")

                pwd = extract_password(reply)
                if pwd:
                    print(f"[+] Parsed password: {pwd}")
                    submitted = br.fill_password_and_submit(pwd)
                    if submitted:
                        print(f"[+] Submitted password {pwd} into form.")
                    # Handle modal and save hint if present
                    modal_hint = br.handle_modal()
                    if modal_hint:
                        store.update_level_summary(level, True, note=f"Dev hint: {modal_hint}")
                    reward = 1.0
                else:
                    reward = score_nearmiss(reply)

                br.screenshot(session_dir / f"level{level:02d}_attempt{global_attempts:02d}.png")

                rec = {
                    "ts": ts_ms(),
                    "level": level,
                    "attempt": global_attempts,
                    "prompt": prompt,
                    "model_rationale": plan.get("why",""),
                    "reply_excerpt": (reply or "")[:600],
                    "parsed_password": pwd,
                    "reward": reward
                }
                write_jsonl(transcript, rec)
                store.append_attempt(rec)

                if pwd:
                    logger.success(f"SOLVED L{level}: {pwd}")
                    store.update_level_summary(level, True, note="Solved via Ollama-proposed prompt", avoid=plan.get("avoid"))
                    # After modal Continue, the level often increments — re-read:
                    new_level = br.get_level()
                    level = new_level if new_level else (level + 1)
                    solved = True
                    break

            if not solved:
                store.update_level_summary(level, False, note="Tried primary/fallbacks; no success", avoid=plan.get("avoid"))
                if global_attempts >= MAX_GLOBAL_ATTEMPTS:
                    logger.warning(f"Max attempts reached ({MAX_GLOBAL_ATTEMPTS}). Stopping.")
                    break

    return transcript
