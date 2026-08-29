# Paste this into ChatGPT or Codex

Repo (public): https://github.com/clearyg3212/edge-desk

```
Review https://github.com/clearyg3212/edge-desk

This is a paper-only Kalshi MLB bot. It must never place live orders.

Read AGENTS.md first, then src/engine.py, src/fees.py, src/thesis.py, src/test_core.py.

Look for:
1. Fee model errors (quadratic 7% fee, ceil on the TOTAL not per-contract)
2. Using 100-bid when ask is missing
3. Generic Poisson spray instead of named theses
4. Gates that can never fire, or that fire on fair prices
5. Matching bugs on Kalshi tickers / MLB team codes
6. Any path that could send an HTTP write to Kalshi

Do not add live trading. Propose patches as a PR-style diff. Keep tests in src/test_core.py green.
```
