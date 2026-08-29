# EDGE DESK — review brief (ChatGPT / Codex / Grok)

Paper-only Kalshi MLB scanner. **Never place live orders. Do not add Kalshi auth, order endpoints, or a live-mode flag.**

## Run

Python 3.10+, stdlib only.

```text
python -m src.test_core
python -m src.main --once
python -m src.main --synthetic-only
```

Windows: `run.bat`. Tests must stay green (22+).

## Architecture (read in this order)

1. `src/config.py` — frozen `paper_mode=True`, `dry_run=True`. Engine refuses to construct if either flips.
2. `src/fees.py` — Kalshi taker fee: `0.07 * n * p * (1-p)`, **ceil the total** to a cent. `realized_pnl_cents` **subtracts that fee**.
3. `src/matching.py` — ticker parse; **away/home order is exact**, not a set.
4. `src/priors.py` + `src/calibrate.py` — empirical YRFI from MLB (prior-year ERA). `ace_tax` uses `two_ace.p`, not 0.41.
5. `src/thesis.py` — **only named theses trade**.
5. `src/eligibility.py` — pregame, confirmed starters, 25m–16h, Coors NRFI veto, half-point totals.
6. `src/engine.py` — ask-only, depth required, crossed books rejected, EV/ROI gates, **caps persist via existing tickets**.
7. `src/scan.py` — public MLB + public Kalshi. Match window 6h. Quote timestamps stored.
8. `src/ledger.py` — paper tickets; settle uses fee-adjusted P&L; **atomic jsonl replace**.
9. `src/test_core.py` — adversarial checks. Add a test if you change a gate.
10. `src/quotes.py` + `src/report.py` — paper **training log**. Every quote, then labels at final. Do not train a net on tickets alone.

## Economic invariants (do not “simplify”)

- Price basis = **executable ask only**. Missing ask = reject. Never `100 - yes_bid`.
- **No depth / size 0 / size None = not executable.** Never paper 10 lots of air.
- Spread < 0 or yes_ask + no_ask < 100 = crossed, reject.
- Closed/unopen status = reject. Quote older than 180s (when timestamp exists) = reject.
- Spread is a liquidity filter, not an EV haircut.
- Accept only if **net EV ≥ 6¢** after fee **and** ROI ≥ 10% **and** model–ask gap ≥ 7¢.
- Price band 28–72¢, spread ≤ 5¢.
- **NO depth** = `yes_bid_size_fp` (buying NO lifts the YES bid). Never `no_ask_size_fp` alone.
- Kalshi scan is **invalid** unless both series fetches succeed. Failed feed ≠ quiet night. No tickets.
- Freshness = page receipt time + page latency, not a fictional `price_updated_ts`. Missing quote ts is allowed if the page is fresh; future ts and slow pages are not.
- Paper fill: wait `exec_latency_sec`, refetch ticker, fill only at the new ask/depth.
- 25m–16h is in **eligibility**, every thesis.
- Game cap is for the life of `game_id`, not the UTC day.
- `DataLock` around load → scan → settle → fill → save.
- Ladder fit **excludes the market being scored** and needs ≥3 other strikes.
- Empty nights are correct. Do not loosen gates so it “looks alive.”

## Review asks

- Fee rounding / EV sign / **realized P&L omitting fees**
- Ask inference / **zero-depth fills**
- Caps that reset every scan
- Ticker/team matching (home/away reversal, DH)
- Thesis firing on fair prices
- Anything that could send an order

If you change behavior, add a failing-then-passing test in `src/test_core.py`.
