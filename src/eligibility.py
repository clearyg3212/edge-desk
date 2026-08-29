from datetime import datetime, timezone
from typing import Optional

from .config import CFG
from .matching import is_half_point
from .parks import is_coors
from .types import KalshiSnap, MlbGame


def minutes_to_pitch(game: MlbGame, now: Optional[datetime] = None) -> float:
    now = now or datetime.now(timezone.utc)
    start = datetime.fromisoformat(game.commence_iso.replace("Z", "+00:00"))
    return (start - now).total_seconds() / 60.0


def eligibility(game: MlbGame, market: KalshiSnap, side: str) -> Optional[str]:
    if game.phase == "void":
        return "postponed"
    if game.phase == "final":
        return "already_final"
    if game.phase == "live":
        return "in_progress"
    if minutes_to_pitch(game) < CFG.min_minutes_to_pitch:
        return "too_close_to_pitch"
    if not game.away_pitcher.id or not game.home_pitcher.id:
        return "starter_unconfirmed"
    if market.kind == "TOTAL":
        if market.line is None:
            return "unmatched"
        if CFG.require_half_point_totals and not is_half_point(market.line):
            return "integer_line"
    if market.kind == "RFI" and side == "NO" and is_coors(game.home_canon, game.venue):
        return "coors_nrfi"
    return None


REASON_LABEL = {
    "edge_ok": "edge",
    "missing_price": "no ask",
    "price_out_of_band": "price band",
    "spread_too_wide": "wide spread",
    "edge_too_small": "EV too small",
    "roi_too_small": "ROI too small",
    "duplicate_ticker": "duplicate",
    "daily_limit": "daily cap",
    "game_limit": "game cap",
    "starter_unconfirmed": "TBD starter",
    "too_close_to_pitch": "inside 25m",
    "in_progress": "live game",
    "already_final": "final",
    "coors_nrfi": "Coors NRFI veto",
    "integer_line": "integer line",
    "postponed": "postponed",
    "unmatched": "unmatched",
    "no_structural_edge": "no thesis",
    "disagreement_too_small": "gap too small",
    "too_early": "too early",
    "thin_sample": "thin sample",
    "live_mode_blocked": "live blocked",
    "thin_book": "no depth",
    "crossed_book": "crossed book",
    "closed_market": "closed",
    "stale_quote": "stale quote",
}
