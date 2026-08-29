# EDGE DESK — Windows paper bot

Paper-only Kalshi MLB scanner. **Never places a live order.**

## Install on Windows

1. Install Python 3.10+ from https://www.python.org/downloads/
   - On the installer, tick **Add python.exe to PATH**
2. On this GitHub page: **Code → Download ZIP**
3. Unzip to Desktop (folder will be `edge-desk-main`)
4. Double-click **run.bat**

That's the whole app. First run prints tests, then scans tonight's MLB vs Kalshi. Most nights it papers **zero** tickets. That's working.

Desktop wallpaper: right-click `wallpaper.jpg` → Set as desktop background.

## What it does

Reads public MLB + public Kalshi. Papers a ticket only if a named thesis still has at least 6 cents expected value after Kalshi's fee. Settled P&L subtracts that fee.

No API key. No pip install.

## Review in ChatGPT or Codex

This repo is **public**. Paste:

> Review https://github.com/clearyg3212/edge-desk — read AGENTS.md first. Paper-only. Do not add live Kalshi orders.

Full prompt: [REVIEW.md](REVIEW.md). Codex: open the repo and follow `AGENTS.md`.
