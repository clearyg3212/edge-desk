from typing import List, Optional

from .config import CFG, OPEN_STATUSES
from .model import poisson_cdf
from .types import KalshiSnap


def survival(line: float, lam: float) -> float:
    return 1.0 - poisson_cdf(int(line), lam)


def _mid_yes(m: KalshiSnap) -> Optional[float]:
    if m.yes_bid is not None and m.yes_ask is not None:
        return (m.yes_bid + m.yes_ask) / 2
    if m.yes_ask is not None and m.no_ask is not None:
        return (m.yes_ask + (100 - m.no_ask)) / 2
    return m.yes_ask


def _usable(m: KalshiSnap) -> bool:
    if (m.status or "").lower() not in OPEN_STATUSES:
        return False
    if not getattr(m, "trading_active", True):
        return False
    if m.kind != "TOTAL" or m.line is None:
        return False
    spread = None
    if m.yes_bid is not None and m.yes_ask is not None:
        spread = m.yes_ask - m.yes_bid
    if spread is None or spread < 0 or spread > CFG.max_spread_cents:
        return False
    if m.yes_ask_size is None or m.yes_ask_size < CFG.min_ask_size:
        return False
    mid = _mid_yes(m)
    if mid is None or mid <= 8 or mid >= 92:
        return False
    return True


def fit_ladder(markets: List[KalshiSnap], exclude_ticker: Optional[str] = None) -> Optional[dict]:
    """Fit λ to *other* unique, clean strikes. Evaluated ticker excluded."""
    by_line = {}
    for m in markets:
        if exclude_ticker and m.ticker == exclude_ticker:
            continue
        if not _usable(m):
            continue
        mid = _mid_yes(m)
        prev = by_line.get(m.line)
        if prev is None or abs((m.yes_ask or 50) - (m.yes_bid or 50)) < abs(prev[2]):
            by_line[m.line] = (m.line, mid / 100.0, abs((m.yes_ask or 50) - (m.yes_bid or 50)))
    points = sorted((line, p) for line, p, _ in by_line.values())
    if len(points) < CFG.ladder_min_points:
        return None
    for i in range(1, len(points)):
        if points[i][1] > points[i - 1][1] + 0.03:
            return None
    best_lam, best_err = 8.5, 1e18
    lam = 5.0
    while lam <= 13.5:
        err = sum((survival(line, lam) - p) ** 2 for line, p in points)
        if err < best_err:
            best_err, best_lam = err, lam
        lam += 0.1
    rmse = (best_err / len(points)) ** 0.5
    if rmse > 0.12:
        return None
    return {"lambda": round(best_lam, 1), "points": len(points), "rmse": round(rmse, 4)}
