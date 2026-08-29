from typing import Optional

from .config import CFG
from .priors import yrfi_p
from .eligibility import minutes_to_pitch
from .ladder import survival
from .parks import is_coors
from .types import KalshiSnap, MlbGame, ModelEstimate


def _both_aces(game: MlbGame) -> bool:
    a, h = game.away_pitcher.era, game.home_pitcher.era
    return a is not None and h is not None and a < 3.3 and h < 3.3


def _both_soft(game: MlbGame) -> bool:
    a, h = game.away_pitcher.era, game.home_pitcher.era
    return a is not None and h is not None and a > 4.85 and h > 4.85


def _thin(game: MlbGame) -> bool:
    a, h = game.away_pitcher.ip, game.home_pitcher.ip
    return a is None or h is None or a < 20 or h < 20


def thesis(
    game: MlbGame,
    market: KalshiSnap,
    side: str,
    ask: float,
    model: ModelEstimate,
    ladder: Optional[dict],
) -> dict:
    mins = minutes_to_pitch(game)

    if market.kind == "TOTAL" and market.line is not None and ladder and ladder["points"] >= CFG.ladder_min_points:
        p_over = survival(market.line, ladder["lambda"])
        p = p_over if side == "YES" else 1 - p_over
        near = abs(market.line - (ladder["lambda"] - 0.5)) <= 1.6
        if near and p * 100 - ask >= CFG.min_disagreement_cents and mins <= CFG.max_hours_to_pitch * 60:
            return {"p": p, "tag": "ladder_kink", "source": "kalshi-ladder", "reject": None}

    if market.kind == "RFI":
        if _thin(game):
            return {"p": 0.5, "tag": "thin_sample", "source": "f1-poisson", "reject": "thin_sample"}
        if _both_aces(game) and side == "YES":
            p = yrfi_p("two_ace")
            return {"p": p, "tag": "ace_tax", "source": "mlb-prior+ace-gate", "reject": None}
        if _both_soft(game) and side == "YES":
            p = yrfi_p("two_soft")
            return {"p": p, "tag": "soft_arm", "source": "mlb-prior+soft-gate", "reject": None}

    if mins > CFG.max_hours_to_pitch * 60:
        return {"p": 0.5, "tag": "too_early", "source": "f1-poisson", "reject": "too_early"}

    wx = any(n in model.notes for n in ("wind-out-20", "wind-out", "wind-in-20", "wind-in", "cold", "hot"))
    if wx and market.kind == "TOTAL" and market.line is not None:
        if mins > CFG.weather_max_minutes:
            return {"p": 0.5, "tag": "stale_weather", "source": "weather", "reject": "too_early"}
        p_over = model.over_prob(market.line)
        p = p_over if side == "YES" else 1 - p_over
        out = any(n.startswith("wind-out") or n == "hot" for n in model.notes)
        inn = any(n.startswith("wind-in") or n == "cold" for n in model.notes)
        dir_ok = (out and side == "YES") or (inn and side == "NO")
        if dir_ok and p * 100 - ask >= CFG.min_disagreement_cents:
            return {"p": p, "tag": "stale_weather", "source": "weather", "reject": None}

    if is_coors(game.home_canon, game.venue) and market.kind == "TOTAL" and side == "NO" and ask <= 46:
        p_under = 1 - model.over_prob(market.line if market.line is not None else 11.5)
        if p_under * 100 - ask >= CFG.min_disagreement_cents:
            return {"p": p_under, "tag": "coors", "source": "coors-fade", "reject": None}

    return {"p": 0.5, "tag": "model_vs_ask", "source": "f1-poisson", "reject": "no_structural_edge"}
