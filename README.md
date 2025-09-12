# HackMerlin LLM Agent — 6 Levels Passed

## Repository
https://github.com/unforgettablexD/hackmerlin

## Demo Video

[level6.webm](https://github.com/user-attachments/assets/b58cf5fa-1e22-4e67-b52b-40071b1c26d6)

## Documentation (PDF)
[HackMerlin LLM Agent — 6 Levels passed.pdf](https://github.com/user-attachments/files/22288539/HackMerlin.LLM.Agent.6.Levels.passed.pdf)


## Key Artifacts
- [Attempts Log (`attempts.jsonl`)](https://github.com/unforgettablexD/hackmerlin/blob/main/session-ollama-20250910-115335/attempts.jsonl)  
- [Level Summaries (`level_summaries.json`)](https://github.com/unforgettablexD/hackmerlin/blob/main/session-ollama-20250910-115335/level_summaries.json)  
- [Transcript (`transcript.jsonl`)](https://github.com/unforgettablexD/hackmerlin/blob/main/session-ollama-20250910-115335/transcript.jsonl)

## Overview
This project implements a browser-automation LLM agent that solves levels on [hackmerlin.io](https://hackmerlin.io).  
- The agent runs a Chromium session via Playwright.  
- It converses with the chat UI, opportunistically submits candidate passwords, and advances levels strictly when the page heading increments (`Level N` → `Level N+1`).  
- Modal hints are captured but **never treated as success**.  
- A persistent memory store logs attempts, avoids repeated wrong guesses, and guides strategy.  
- A Strategist module encodes rules and tactics (length, vowels/consonants, probing indices) and always outputs strict JSON actions (`ask` or `submit`).  
- The runloop executes actions, verifies success, saves transcripts, screenshots, and think logs.  

## Results
- Successfully advanced **6 levels** in an automated run.  
- All supporting evidence (logs, transcripts, screenshots) is included in the repo and summarized in the attached PDF.  

---
