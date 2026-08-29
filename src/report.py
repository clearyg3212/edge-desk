"""Calibration from the paper log. Last pregame quote per ticker:side, joined to finals."""
from __future__ import annotations

from collections import defaultdict

from .config import CFG
from .quotes import load_outcomes, load_quotes


def _pregame_last(quotes: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for q in quotes:
        if q.get("phase") not in (None, "pregame"):
            continue
        key = f"{q.get('ticker')}:{q.get('side')}"
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
    last = _pregame_last(quotes)
    labeled = [q for q in last if q.get("game_id") in outcomes and outcomes[q["game_id"]].phase == "final"]
    pending = len(last) - len(labeled)

    print("EDGE DESK  ·  paper log")
    print(f"snapshots {len(quotes)}  unique last-quotes {len(last)}  labeled {len(labeled)}  pending {pending}")
    print(f"files  {CFG.data_dir / 'quotes.jsonl'}")
    print(f"       {CFG.data_dir / 'outcomes.jsonl'}")
    print()

    buckets: dict[str, list] = defaultdict(list)
    for q in labeled:
        o = outcomes[q["game_id"]]
        if q.get("kind") == "RFI" and o.yrfi is not None:
            won_yes = o.yrfi == 1
        elif q.get("kind") == "TOTAL" and o.total_runs is not None and q.get("line") is not None:
            won_yes = o.total_runs > q["line"]
        else:
            continue
        we = (q.get("side") == "YES" and won_yes) or (q.get("side") == "NO" and not won_yes)
        buckets[str(q.get("tag") or "none")].append((q, we, o))
        buckets["ALL"].append((q, we, o))

    print(f"{'tag':16} {'n':>5} {'hit':>6} {'ask':>7} {'p':>7} {'brier':>7}")
    for tag in sorted(buckets, key=lambda t: (t != "ALL", t)):
        rows = buckets[tag]
        n = len(rows)
        hits = sum(1 for _, we, _ in rows if we)
        asks = [r[0].get("ask") or 0 for r in rows]
        ps = [r[0].get("model_p") or 0.5 for r in rows]
        # Brier vs realized YES if side YES else invert
        briers = []
        for q, we, o in rows:
            y = 1.0 if we else 0.0
            p = float(q.get("model_p") or 0.5)
            briers.append((p - y) ** 2)
        avg_ask = sum(asks) / n if n else 0
        avg_p = 100 * sum(ps) / n if n else 0
        avg_b = sum(briers) / n if n else 0
        print(f"{tag:16} {n:5d} {_rate(n, hits):>6} {avg_ask:6.1f}¢ {avg_p:6.1f}% {avg_b:7.3f}")

    if not labeled:
        print("\nNo settled quotes yet. Run the bot through a slate, then again after games go final.")
        print("python -m src.main --once")
        print("python -m src.report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
