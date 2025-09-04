from __future__ import annotations
import argparse
from merlin_agent.runloop_llm import run_session_llm


def parse_args():
    p = argparse.ArgumentParser(description="HackMerlin Agent - Ollama strategist")
    p.add_argument("--headless", action="store_true", default=False, help="Run headless browser")
    p.add_argument("--debug", action="store_true", default=False, help="(reserved)")
    return p.parse_args()

def main():
    args = parse_args()
    log = run_session_llm(headless=args.headless, debug=args.debug)
    print(f"Transcript saved to: {log}")

if __name__ == "__main__":
    main()
