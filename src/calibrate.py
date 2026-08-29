"""Fit YRFI priors from MLB history. No Kalshi, no live orders.

Tags starters by *prior-year* ERA so the label is known before first pitch.
Writes src/priors_default.json and data/priors.json.

    python -m src.calibrate
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .config import CFG, ROOT
from .priors import PACKAGED, reload

UA = {"User-Agent": "edge-desk-calibrate/1.0", "Accept": "application/json"}
# (season to score, prior year for ERA, opening day, last day)
WINDOWS = [
    (2023, 2022, "2023-03-30", "2023-10-01"),
    (2024, 2023, "2024-03-28", "2024-09-30"),
    (2025, 2024, "2025-03-27", "2025-09-28"),
    (2026, 2025, "2026-03-27", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
]
ACE = 3.3
SOFT = 4.85
IP_MIN = 20
SHRINK_K = 50.0
LEAGUE = 0.49


def _get(url: str):
    last = None
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(0.7 * (i + 1))
    raise last


def season_era(year: int) -> dict:
    url = (
        "https://statsapi.mlb.com/api/v1/stats?stats=season&group=pitching"
        f"&season={year}&sportIds=1&limit=800&playerPool=all"
    )
    data = _get(url)
    out = {}
    splits = ((data.get("stats") or [{}])[0].get("splits") or [])
    for s in splits:
        pid = int((s.get("player") or {}).get("id") or 0)
        st = s.get("stat") or {}
        try:
            era = float(st.get("era"))
            ip = float(str(st.get("inningsPitched") or "0").split(".")[0])
        except (TypeError, ValueError):
            continue
        if pid and ip >= IP_MIN:
            out[pid] = era
    return out


def schedule(start: str, end: str) -> list:
    url = (
        "https://statsapi.mlb.com/api/v1/schedule?sportId=1"
        f"&startDate={start}&endDate={end}&hydrate=probablePitcher,linescore"
    )
    data = _get(url)
    games = []
    for d in data.get("dates") or []:
        games.extend(d.get("games") or [])
    return games


def _f1(g) -> int | None:
    inns = ((g.get("linescore") or {}).get("innings") or [])
    if not inns:
        return None
    a = (inns[0].get("away") or {}).get("runs")
    h = (inns[0].get("home") or {}).get("runs")
    if a is None or h is None:
        return None
    return int(a) + int(h)


def _pid(g, side) -> int | None:
    p = ((g.get("teams") or {}).get(side) or {}).get("probablePitcher") or {}
    return p.get("id")


def _block(n: int, hits: int) -> dict:
    raw = hits / n if n else LEAGUE
    se = math.sqrt(raw * (1 - raw) / n) if n else 0.0
    p = (hits + LEAGUE * SHRINK_K) / (n + SHRINK_K) if n else LEAGUE
    return {
        "n": n,
        "hits": hits,
        "raw": round(raw, 4),
        "p": round(min(0.72, max(0.28, p)), 4),
        "se": round(se, 4),
    }


def run() -> dict:
    buckets = defaultdict(lambda: [0, 0])
    for season, prior, start, end in WINDOWS:
        print(f"ERA {prior} → games {season} …")
        try:
            era = season_era(prior)
            games = schedule(start, end)
        except Exception as e:
            print(f"  skip: {e}")
            continue
        print(f"  pitchers {len(era)}  games {len(games)}")
        for g in games:
            if (g.get("status") or {}).get("abstractGameState") != "Final":
                continue
            runs = _f1(g)
            if runs is None:
                continue
            a, h = _pid(g, "away"), _pid(g, "home")
            if not a or not h:
                continue
            ea, eh = era.get(a), era.get(h)
            yr = 1 if runs > 0 else 0
            if ea is None or eh is None:
                buckets["missing_prior"][0] += 1
                buckets["missing_prior"][1] += yr
                continue
            buckets["league"][0] += 1
            buckets["league"][1] += yr
            if ea < ACE and eh < ACE:
                buckets["two_ace"][0] += 1
                buckets["two_ace"][1] += yr
            if ea > SOFT and eh > SOFT:
                buckets["two_soft"][0] += 1
                buckets["two_soft"][1] += yr
            if ea < ACE or eh < ACE:
                buckets["one_ace"][0] += 1
                buckets["one_ace"][1] += yr

    out = {
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "prior-year ERA, F1 runs>0, shrink k=50 toward 0.49",
        "source": "mlb-statsapi",
        "league": _block(*buckets["league"]),
        "two_ace": _block(*buckets["two_ace"]),
        "two_soft": _block(*buckets["two_soft"]),
        "one_ace": _block(*buckets["one_ace"]),
        "missing_prior": _block(*buckets["missing_prior"]),
    }
    return out


def _ev_table(p: float) -> list:
    from .fees import net_ev_cents

    rows = []
    for ask in (28, 32, 36, 40, 45, 50, 55):
        ev = net_ev_cents(p, ask, 1)
        rows.append({"ask": ask, "net_ev": ev["net_ev_cents"], "take": ev["net_ev_cents"] >= 6 and (p * 100 - ask) >= 7})
    return rows


def main() -> int:
    print("EDGE DESK  ·  calibrate YRFI priors from MLB (paper, no Kalshi)")
    priors = run()
    priors["ace_tax_ev_if_this_p"] = _ev_table(priors["two_ace"]["p"])
    text = json.dumps(priors, indent=2)
    CFG.data_dir.mkdir(parents=True, exist_ok=True)
    live = CFG.data_dir / "priors.json"
    live.write_text(text, encoding="utf-8")
    PACKAGED.write_text(text, encoding="utf-8")
    reload()
    print()
    print(f"{'tag':16} {'n':>6} {'yrfi':>6} {'raw':>7} {'shrunk':>8} {'se':>7}")
    for tag in ("league", "two_ace", "one_ace", "two_soft", "missing_prior"):
        b = priors[tag]
        print(f"{tag:16} {b['n']:6d} {b['hits']:6d} {b['raw']:7.3f} {b['p']:8.3f} {b['se']:7.3f}")
    print()
    print("If two-ace YRFI is this p, paper-take at ask:")
    for row in priors["ace_tax_ev_if_this_p"]:
        mark = "TAKE" if row["take"] else "sit"
        print(f"  {row['ask']:2d}¢  net EV {row['net_ev']:5.1f}¢  {mark}")
    print(f"\nwrote {live}")
    print(f"wrote {PACKAGED}")
    print("thesis.py reads two_ace.p for ace_tax. Re-run this after the season.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
