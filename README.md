# EDGE DESK — paper MLB vs Kalshi

A **paper-only** bot. It never logs into Kalshi, never sends an order, never needs an API key.

It reads public MLB (starters, weather, scores) and public Kalshi (RFI + totals), then papers a ticket **only** if a named thesis still has ≥6¢ expected value **after** Kalshi’s fee.

## Run on your PC

Needs **Python 3.10+**. No pip packages.

```text
Windows:  double-click run.bat
          or:  py -3 -m src.test_core
               py -3 -m src.main --once

          paper log (leave open):  double-click run_loop.bat
          morning after:           py -3 -m src.report
          rebuild YRFI priors:     py -3 -m src.calibrate

Mac/Linux:  chmod +x run.sh && ./run.sh
            python3 -m src.test_core
            python3 -m src.main --once
            python3 -m src.main --loop 30
            python3 -m src.report
            python3 -m src.calibrate
```

`--synthetic-only` skips the network and just proves the engine.

## When it trades (paper)

Fail any step → sit.

1. Pregame, confirmed starters with 20+ IP, 25 min–16 h to pitch  
2. Real ask on the book, 28–72¢, spread ≤5¢  
3. A **story**, not “the model disagrees”:
   - Kalshi totals ladder disagrees with itself
   - Two aces and YRFI is still cheap (public stuffed NRFI)
   - Two bad starters, YRFI hasn’t moved
   - Serious wind/heat/cold, inside 2.5 hours, right direction
   - Coors-under fade  
4. After the 7% quadratic fee: **6¢ net EV**, **10% ROI**, **7¢** vs the ask  
5. One ticket per game, four a day, tiny size (0.25% of a $10k paper bank)

Most nights print **zero**. That is the point.

## Files it writes

| path | what |
|---|---|
| `data/quotes.jsonl` | **training log** — every quote, pass or take |
| `data/outcomes.jsonl` | F1 / total when the game is final |
| `data/tickets.jsonl` | paper blotter; fee-adjusted P&L |
| `logs/decisions.jsonl` | raw engine dump |
| `wallpaper.jpg` | 1920×1080 desktop background |
| `thumbnail.png` | square icon |

Start the log: **`run_loop.bat`**. Next morning: `py -3 -m src.report`. That is how the edge gets trained. Do not go live first.

## Hard rules

- `paper_mode` and `dry_run` are frozen on. Flip them and the engine refuses to start.  
- Price = executable ask only. Missing ask = pass. Never `100 − yes_bid`.  
- Spread is a liquidity filter, not an EV haircut.  
- Fee: `0.07 × n × p × (1−p)`, round the **total** up to a cent, then share.

Desktop wallpaper: right-click `wallpaper.jpg` → Set as desktop background.
