from __future__ import annotations
import time
from pathlib import Path
from loguru import logger
from .browser import MerlinBrowser
from .parser import extract_password, score_nearmiss
from .memory import ExperienceStore
from .ollama_client import OllamaClient
from .strategist import choose_next_prompt
from .utils import RUNS, write_jsonl, ts_ms


def _wait_for_level_increment(br: MerlinBrowser, prev_level: int, timeout_ms: int = 7000) -> int | None:
    """
    Poll the 'Level N' heading until it increases beyond prev_level.
    Returns the new level or None if it didn't change in time.
    """
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        lv = br.get_level()
        if isinstance(lv, int) and lv > prev_level:
            return lv
        # small sleep to avoid hammering the page
        time.sleep(0.15)
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

        # Single source of truth for level = page heading
        level = br.get_level() or 1
        global_attempts = 0
        MAX_GLOBAL_ATTEMPTS = 60
        prev_level = 0

        while global_attempts < MAX_GLOBAL_ATTEMPTS:
            logger.info(f"=== OLLAMA MODE: Level {level} ===")

            # Close any stray modal; do NOT treat this as success
            _ = br.handle_modal()
            br.page.wait_for_timeout(10000)  # 10s
            new_level = _wait_for_level_increment(br, prev_level, timeout_ms=10000)

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

                # Re-read level just for display (not considered success)
                dom_level = br.get_level()
                if isinstance(dom_level, int):
                    level = dom_level

                print("\n================ EXCHANGE ================")
                print(f"Level: {level}")
                print(f">>> PROMPT SENT:\n{prompt}\n")
                print(f"<<< REPLY RECEIVED:\n{reply}\n")
                print("==========================================\n")

                # Try to extract a password
                # Try to extract a password
                pwd = extract_password(reply)
                success_pwd = None
                reward = 0.0

                if pwd:
                    print(f"[+] Parsed password: {pwd}")

                    # define prev_level BEFORE submit
                    prev_level = level

                    submitted = br.fill_password_and_submit(pwd)
                    if submitted:
                        print(f"[+] Submitted password '{pwd}' into form.")

                        # Close modal (capture hint, but don't treat as success)
                        modal_hint = br.handle_modal()
                        if modal_hint:
                            store.update_level_summary(prev_level, False, note=f"Dev hint: {modal_hint}")

                        # (optional) dump DOM for debugging before polling heading
                        br.dump_dom(session_dir / f"after_submit_l{prev_level}_attempt{global_attempts}.html")

                        # give UI a tick, then poll for heading increment
                        br.page.wait_for_timeout(500)
                        new_level = _wait_for_level_increment(br, prev_level, timeout_ms=10000)

                        if isinstance(new_level, int) and new_level > prev_level:
                            print(f"[+] ACCEPTED: Level advanced {prev_level} → {new_level}")
                            success_pwd = pwd
                            reward = 1.0
                            logger.success(f"SOLVED L{prev_level}: {pwd}")
                            store.update_level_summary(prev_level, True, note=f"Solved with prompt: {prompt}", avoid=plan.get("avoid"))
                            level = new_level  # authoritative
                            solved = True
                        else:
                            print("[!] Submission did not advance level; treating as not solved.")
                    else:
                        print("[WARN] Could not click/submit the password button.")
                else:
                    # no password parsed; compute a near-miss reward
                    reward = score_nearmiss(reply)


                # Save screenshot & attempt record
                br.screenshot(session_dir / f"level{level:02d}_attempt{global_attempts:02d}.png")
                rec = {
                    "ts": ts_ms(),
                    "level": level,
                    "attempt": global_attempts,
                    "prompt": prompt,
                    "model_rationale": plan.get("why", ""),
                    "reply_excerpt": (reply or "")[:600],
                    "parsed_password": success_pwd or pwd,
                    "reward": reward,
                }
                write_jsonl(transcript, rec)
                store.append_attempt(rec)

                if solved:
                    break  # move to next loop/level

            if not solved:
                store.update_level_summary(level, False, note="Tried primary/fallbacks; no success", avoid=plan.get("avoid"))
                if global_attempts >= MAX_GLOBAL_ATTEMPTS:
                    logger.warning(f"Max attempts reached ({MAX_GLOBAL_ATTEMPTS}). Stopping.")
                    break

    return transcript
