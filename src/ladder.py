from typing import List, Optional

from .config import CFG
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


def fit_ladder(markets: List[KalshiSnap], exclude_ticker: Optional[str] = None) -> Optional[dict]:
    """Fit λ to *other* strikes. The evaluated market is excluded so this is not circular."""
    points = []
    for m in markets:
        if exclude_ticker and m.ticker == exclude_ticker:
            continue
        if m.kind != "TOTAL" or m.line is None:
            continue
        mid = _mid_yes(m)
        if mid is None or mid <= 8 or mid >= 92:
            continue
        points.append((m.line, mid / 100.0))
    if len(points) < CFG.ladder_min_points:
        return None
    best_lam, best_err = 8.5, 1e18
    lam = 5.0
    while lam <= 13.5:
        err = sum((survival(line, lam) - p) ** 2 for line, p in points)
        if err < best_err:
            best_err, best_lam = err, lam
        lam += 0.1
    return {"lambda": round(best_lam, 1), "points": len(points)}
