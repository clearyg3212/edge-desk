from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from .config import CFG, OPEN_STATUSES
from .eligibility import eligibility
from .fees import kalshi_taker_fee_cents, net_ev_cents
from .ladder import fit_ladder
from .model import project_game
from .thesis import thesis
from .types import Decision, KalshiSnap, MlbGame, ModelEstimate


def _ask(market: KalshiSnap, side: str):
    if side == "YES":
        if market.yes_ask is not None and market.yes_bid is not None:
            spread = market.yes_ask - market.yes_bid
        else:
            spread = 99
        return market.yes_ask, spread, market.yes_ask_size
    if market.no_ask is not None and market.no_bid is not None:
        spread = market.no_ask - market.no_bid
    else:
        spread = 99
    return market.no_ask, spread, market.no_ask_size


def _size(ask: float, ask_size: Optional[float]) -> int:
    if ask_size is None or ask_size < CFG.min_ask_size:
        return 0
    risk = CFG.paper_bankroll * (CFG.risk_per_trade_pct / 100.0)
    n = int(risk / max(0.01, ask / 100.0))
    n = max(1, min(n, CFG.max_contracts_per_trade, int(ask_size)))
    return n


def _base(**kw) -> Decision:
    defaults = dict(
        ticker="", game_id="", kind="", side="", line=None, ask_cents=0.0, spread_cents=99.0,
        model_prob=0.5, raw_ev=-999.0, fee=0.0, net_ev=-999.0, roi=-999.0, size=0,
        accepted=False, reason="missing_price", reason_tag="none", source="f1-poisson",
        fee_total=0.0, quoted_at=None, observed_at=None, ask_size=None,
    )
    defaults.update(kw)
    return Decision(**defaults)


def parse_iso(iso: Optional[str]) -> Optional[datetime]:
    if not iso or not isinstance(iso, str):
        return None
    s = iso.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_age_sec(iso: Optional[str], now: datetime) -> Optional[float]:
    ts = parse_iso(iso)
    if ts is None:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds()


def score(game: MlbGame, market: KalshiSnap, side: str, model: ModelEstimate, ladder, now: Optional[datetime] = None) -> Decision:
    CFG.assert_paper_safe()
    now = now or datetime.now(timezone.utc)
    observed = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    ask, spread, ask_size = _ask(market, side)
    d = _base(
        ticker=market.ticker, game_id=game.game_id, kind=market.kind, side=side,
        line=market.line, ask_cents=ask or 0.0, spread_cents=spread,
        quoted_at=market.quoted_at, observed_at=market.observed_at or observed,
        ask_size=ask_size,
    )
    gate = eligibility(game, market, side)
    if gate:
        d.reason, d.reason_tag = gate, gate
        return d
    if (market.status or "").lower() not in OPEN_STATUSES:
        d.reason, d.reason_tag = "closed_market", "closed_market"
        return d
    if not getattr(market, "trading_active", True):
        d.reason, d.reason_tag = "exchange_paused", "exchange_paused"
        return d
    if ask is None:
        d.reason = "missing_price"
        return d
    d.ask_cents = ask
    if spread < 0:
        d.reason, d.reason_tag = "crossed_book", "crossed_book"
        return d
    if market.yes_ask is not None and market.no_ask is not None and market.yes_ask + market.no_ask < 100:
        d.reason, d.reason_tag = "crossed_book", "crossed_book"
        return d
    if ask < CFG.min_price_cents or ask > CFG.max_price_cents:
        d.reason = "price_out_of_band"
        return d
    if spread > CFG.max_spread_cents:
        d.reason = "spread_too_wide"
        return d
    if market.page_latency_sec and market.page_latency_sec > CFG.max_page_latency_sec:
        d.reason, d.reason_tag = "stale_quote", "stale_quote"
        return d
    obs_age = _iso_age_sec(market.observed_at, now)
    if obs_age is not None and obs_age > CFG.max_quote_age_sec:
        d.reason, d.reason_tag = "stale_quote", "stale_quote"
        return d
    # quoted_at (Kalshi updated_time) is metadata — never use it for freshness.
    th = thesis(game, market, side, ask, model, ladder)
    d.model_prob, d.reason_tag, d.source = th["p"], th["tag"], th["source"]
    if th["reject"]:
        d.reason = th["reject"]
        return d
    if th["p"] * 100 - ask < CFG.min_disagreement_cents:
        d.reason = "disagreement_too_small"
        return d
    if ask_size is None or ask_size < CFG.min_ask_size:
        d.reason, d.reason_tag = "thin_book", "thin_book"
        return d
    size = _size(ask, ask_size)
    if size < 1:
        d.reason, d.reason_tag = "thin_book", "thin_book"
        return d
    ev = net_ev_cents(th["p"], ask, size, CFG.fee_coefficient)
    fee_total = kalshi_taker_fee_cents(ask, size, CFG.fee_coefficient)
    d.size, d.raw_ev, d.fee, d.net_ev, d.roi, d.fee_total = (
        size, ev["raw_ev_cents"], ev["fee_cents"], ev["net_ev_cents"], ev["expected_roi"], fee_total,
    )
    if d.net_ev < CFG.min_net_edge_cents:
        d.reason = "edge_too_small"
        return d
    if d.roi < CFG.min_expected_roi:
        d.reason = "roi_too_small"
        return d
    d.accepted, d.reason = True, "edge_ok"
    return d


def _seed_caps(existing: Iterable) -> tuple:
    et = ZoneInfo("America/New_York")
    today = datetime.now(et).date().isoformat()
    daily, per_game, seen = 0, {}, set()
    for t in existing or []:
        status = getattr(t, "status", None) or (t.get("status") if isinstance(t, dict) else None)
        if status == "void":
            continue
        gid = getattr(t, "game_id", None) or (t.get("game_id") if isinstance(t, dict) else "")
        ticker = getattr(t, "ticker", None) or (t.get("ticker") if isinstance(t, dict) else "")
        per_game[gid] = per_game.get(gid, 0) + 1
        if ticker:
            seen.add(ticker)
        opened = getattr(t, "opened_at", None) or (t.get("opened_at") if isinstance(t, dict) else "") or ""
        try:
            opened_day = datetime.fromisoformat(opened.replace("Z", "+00:00")).astimezone(et).date().isoformat()
        except ValueError:
            opened_day = opened[:10]
        if opened_day == today:
            daily += 1
    return daily, per_game, seen


def evaluate_slate(
    games: List[MlbGame],
    markets: List[KalshiSnap],
    existing_tickets: Optional[List] = None,
) -> List[Decision]:
    CFG.assert_paper_safe()
    uniq = {}
    for m in markets:
        prev = uniq.get(m.ticker)
        if prev is None or (m.observed_at or "") >= (prev.observed_at or ""):
            uniq[m.ticker] = m
    markets = list(uniq.values())
    by_id = {g.game_id: g for g in games}
    models = {g.game_id: project_game(g) for g in games}
    totals: Dict[str, List[KalshiSnap]] = {}
    for m in markets:
        if m.kind == "TOTAL" and m.game_id:
            totals.setdefault(m.game_id, []).append(m)

    scored: List[Decision] = []
    for m in markets:
        game = by_id.get(m.game_id or "")
        if not game:
            scored.append(_base(ticker=m.ticker, kind=m.kind, line=m.line, ask_cents=m.yes_ask or 0,
                                reason="unmatched", reason_tag="unmatched", side="YES",
                                quoted_at=m.quoted_at, observed_at=m.observed_at))
            continue
        model = models[game.game_id]
        others = [x for x in totals.get(game.game_id, []) if x.ticker != m.ticker]
        ladder = fit_ladder(others, exclude_ticker=m.ticker)
        if m.kind == "RFI":
            scored.append(score(game, m, "YES", model, ladder))
            scored.append(score(game, m, "NO", model, ladder))
        elif m.kind == "TOTAL" and m.line is not None:
            scored.append(score(game, m, "YES", model, ladder))
            scored.append(score(game, m, "NO", model, ladder))

    ranked = sorted(scored, key=lambda d: d.net_ev, reverse=True)
    daily, per_game, seen = _seed_caps(existing_tickets)
    final = {}
    for d in ranked:
        key = f"{d.ticker}:{d.side}"
        if not d.accepted:
            final.setdefault(key, d)
            continue
        if key in final and final[key].accepted:
            continue
        if d.ticker in seen:
            d.accepted, d.reason = False, "duplicate_ticker"
            final.setdefault(key, d)
            continue
        elif daily >= CFG.max_daily_positions:
            d.accepted, d.reason = False, "daily_limit"
        elif per_game.get(d.game_id, 0) >= CFG.max_positions_per_game:
            d.accepted, d.reason = False, "game_limit"
        else:
            seen.add(d.ticker)
            daily += 1
            per_game[d.game_id] = per_game.get(d.game_id, 0) + 1
        final[key] = d
    out = list(final.values())
    out.sort(key=lambda d: (not d.accepted, -d.net_ev))
    return out
