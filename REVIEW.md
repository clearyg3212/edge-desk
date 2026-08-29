# Paste this into ChatGPT or Codex

Repo (public): https://github.com/clearyg3212/edge-desk

Current HEAD should include `src/calibrate.py`, `src/priors_default.json`, `src/lock.py`, `src/quotes.py`.

```
Review https://github.com/clearyg3212/edge-desk

Paper-only Kalshi MLB bot. Must never place a live order.

Read AGENTS.md first. Then src/scan.py, src/engine.py, src/thesis.py,
src/fees.py, src/priors.py, src/calibrate.py, src/ledger.py, src/lock.py,
src/quotes.py, src/test_core.py.

Prior audits already fixed:
- fees omitted from realized P&L
- zero/missing YES depth treated as executable
- daily/game caps resetting each process
- NO/under depth (must use yes_bid_size_fp)
- dead Kalshi feed looking like a quiet night
- 16h window bypassed by ace_tax
- game cap dying at UTC midnight
- circular ladder fitting the evaluated strike
- hardcoded 41% ace_tax prior

Look for remaining bugs, especially:
1. Fee model (quadratic 7%, ceil on the TOTAL)
2. Missing ask inferred as 100-bid on the YES side
3. NO/under still thin_book on a realistic Kalshi payload
   (yes_ask_size_fp + yes_bid_size_fp, no no_ask_size_fp)
4. kalshi_ok=True on a failed or partial series fetch
5. Time window not applied to every thesis
6. Matching (home/away reversal, doubleheaders)
7. confirm_paper / refetch skipped or using the stale ask
8. File lock not covering load→evaluate→settle→fill→save
9. Generic Poisson spray instead of named theses
10. Any HTTP write to Kalshi

Claims you should NOT let slide:
- Fitted two_ace YRFI ≈ 48.8% (n=414) is a BASEBALL rate.
  It is not evidence Kalshi misprices that rate.
- Paper P&L is simulated. Ready for live trading: no.

Do not add live trading. Propose a PR-style diff. Keep
`python -m src.test_core` green.
```
