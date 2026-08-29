"""Calibration: last YES quote ≥30m before pitch. Tickets reported separately."""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .config import CFG
from .engine import parse_iso
from .ledger import load_tickets
from .quotes import load_outcomes, load_quotes


def _minutes_before(q: dict) -> Optional[float]:
    start = parse_iso(q.get("commence"))
    ts = parse_iso(q.get("ts"))
    if start is None or ts is None:
        return None
    return (start - ts).total_seconds() / 60.0


def _yes_last_eligible(quotes: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for q in quotes:
        if q.get("event") == "execution_attempt":
            continue
        if q.get("side") != "YES":
            continue
        if q.get("phase") not in (None, "pregame"):
            continue
        mins = _minutes_before(q)
        if mins is None or mins < 30:
            continue
        key = str(q.get("ticker") or "")
        prev = best.get(key)
        if prev is None or str(q.get("ts") or "") >= str(prev.get("ts") or ""):
            best[key] = q
    return list(best.values())


def _rate(n: int, k: int) -> str:
    if n == 0:
        return "—"
    return f"{k / n:.3f}"


def main() -> int:
    quotes = load_quotes()
    outcomes = load_outcomes()
    last = _yes_last_eligible(quotes)
    labeled = [q for q in last if q.get("game_id") in outcomes and outcomes[q["game_id"]].phase == "final"]
    attempts = [q for q in quotes if q.get("event") == "execution_attempt"]
    fills = [q for q in attempts if q.get("filled")]
    tickets = load_tickets()
    settled = [t for t in tickets if t.status == "settled"]
    pnl = sum(t.pnl_cents or 0 for t in settled)

    print("EDGE DESK  ·  paper log")
    print(f"YES quotes (T-30m+) {len(last)}  labeled {len(labeled)}")
    print(f"execution attempts {len(attempts)}  fills {len(fills)}")
    print(f"tickets settled {len(settled)}  P&L {pnl/100:.2f} USD (fees included)")
    print(f"files  {CFG.data_dir / 'quotes.jsonl'}")
    print(f"       {CFG.data_dir / 'tickets.jsonl'}")
    print()

    buckets: dict[str, list] = defaultdict(list)
    for q in labeled:
        o = outcomes[q["game_id"]]
        if q.get("kind") == "RFI" and o.yrfi is not None:
            y = float(o.yrfi)
        elif q.get("kind") == "TOTAL" and o.total_runs is not None and q.get("line") is not None:
            y = 1.0 if o.total_runs > q["line"] else 0.0
        else:
            continue
        p = float(q.get("model_p") or 0.5)
        buckets[str(q.get("tag") or "none")].append((q, y, p))
        buckets["ALL"].append((q, y, p))

    print("calibration  (YES probability only, one row per market)")
    print(f"{'tag':16} {'n':>5} {'yrfi':>6} {'ask':>7} {'p':>7} {'brier':>7}")
    for tag in sorted(buckets, key=lambda t: (t != "ALL", t)):
        rows = buckets[tag]
        n = len(rows)
        hits = sum(1 for _, y, _ in rows if y >= 1)
        asks = [r[0].get("ask") or 0 for r in rows]
        brier = sum((p - y) ** 2 for _, y, p in rows) / n if n else 0
        avg_ask = sum(asks) / n if n else 0
        avg_p = 100 * sum(p for _, _, p in rows) / n if n else 0
        print(f"{tag:16} {n:5d} {_rate(n, hits):>6} {avg_ask:6.1f}¢ {avg_p:6.1f}% {brier:7.3f}")

    print()
    print("confirmed tickets")
    if not settled:
        print("  none yet")
    else:
        wins = sum(1 for t in settled if (t.pnl_cents or 0) > 0)
        print(f"  n={len(settled)}  wins={wins}  P&L={pnl/100:.2f} USD")

    if not labeled and not settled:
        print("\nNo labeled YES quotes yet. Leave run_loop.bat open through first pitch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
