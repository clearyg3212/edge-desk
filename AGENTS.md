# EDGE DESK — review brief (ChatGPT / Codex / Grok)

Paper-only Kalshi MLB scanner. **Never place live orders. Do not add Kalshi auth, order endpoints, or a live-mode flag.**

## Run

Python 3.10+, stdlib only.

```text
python -m src.test_core
python -m src.main --once
python -m src.main --synthetic-only
```

Windows: `run.bat`. Tests must stay green.

## Architecture (read in this order)

1. `src/config.py` — frozen `paper_mode=True`, `dry_run=True`. Engine refuses to construct if either flips.
2. `src/fees.py` — Kalshi taker fee: `0.07 * n * p * (1-p)`, **ceil the total** to a cent, then share per contract.
3. `src/matching.py` — ticker parse (`KXMLBRFI` / `KXMLBTOTAL`), team aliases, half-point totals.
4. `src/thesis.py` — **only named theses trade**. Generic Poisson-vs-ask is `no_structural_edge`.
5. `src/eligibility.py` — pregame, confirmed starters, 25m–16h, Coors NRFI veto, half-point totals.
6. `src/engine.py` — ask-only pricing, EV/ROI/disagreement gates, 1/game, 4/day, tiny size.
7. `src/scan.py` — public MLB Stats API + public Kalshi markets. No API key.
8. `src/ledger.py` — paper tickets; settle from final MLB linescore. No money moves.
9. `src/test_core.py` — adversarial checks. Add a test if you change a gate.

## Economic invariants (do not “simplify”)

- Price basis = **executable ask only**. Missing ask = reject. Never `100 - yes_bid`.
- Spread is a liquidity filter, not an EV haircut.
- Accept only if **net EV ≥ 6¢** after fee **and** ROI ≥ 10% **and** model–ask gap ≥ 7¢.
- Price band 28–72¢, spread ≤ 5¢.
- Structural thesis required: `ladder_kink`, `ace_tax` (two aces, YRFI ask ≤ 36¢), `soft_arm`, weather inside 2.5h, Coors-under fade.
- Empty nights are correct. Do not loosen gates so it “looks alive.”

## Review asks

- Fee rounding / EV sign errors
- Ask inference bugs
- Ticker/team matching misses (doubleheaders, ATH/OAK, SF/SFG)
- Thesis firing on fair prices (ace_tax at 50¢ must reject)
- Anything that could send an order

If you change behavior, add a failing-then-passing test in `src/test_core.py` and keep `main` exercising synthetic accept + reject.
