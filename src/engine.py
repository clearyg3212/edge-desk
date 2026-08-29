from typing import Dict, List, Optional

from .config import CFG
from .eligibility import eligibility
from .fees import net_ev_cents
from .ladder import fit_ladder
from .model import project_game
from .thesis import thesis
from .types import Decision, KalshiSnap, MlbGame, ModelEstimate


def _ask(market: KalshiSnap, side: str):
    if side == "YES":
        spread = (market.yes_ask - market.yes_bid) if market.yes_ask is not None and market.yes_bid is not None else 99
        return market.yes_ask, spread, market.yes_ask_size
    spread = (market.no_ask - market.no_bid) if market.no_ask is not None and market.no_bid is not None else 99
    return market.no_ask, spread, market.no_ask_size


def _size(ask: float, ask_size: Optional[float]) -> int:
    risk = CFG.paper_bankroll * (CFG.risk_per_trade_pct / 100.0)
    n = int(risk / max(0.01, ask / 100.0))
    n = max(1, min(n, CFG.max_contracts_per_trade))
    if ask_size and ask_size > 0:
        n = min(n, max(1, int(ask_size)))
    return n


def _base(**kw) -> Decision:
    defaults = dict(
        ticker="", game_id="", kind="", side="", line=None, ask_cents=0.0, spread_cents=99.0,
        model_prob=0.5, raw_ev=-999.0, fee=0.0, net_ev=-999.0, roi=-999.0, size=0,
        accepted=False, reason="missing_price", reason_tag="none", source="f1-poisson",
    )
    defaults.update(kw)
    return Decision(**defaults)


def score(game: MlbGame, market: KalshiSnap, side: str, model: ModelEstimate, ladder) -> Decision:
    CFG.assert_paper_safe()
    ask, spread, ask_size = _ask(market, side)
    d = _base(
        ticker=market.ticker, game_id=game.game_id, kind=market.kind, side=side,
        line=market.line, ask_cents=ask or 0.0, spread_cents=spread,
    )
    gate = eligibility(game, market, side)
    if gate:
        d.reason, d.reason_tag = gate, gate
        return d
    if ask is None:
        d.reason = "missing_price"
        return d
    d.ask_cents = ask
    if ask < CFG.min_price_cents or ask > CFG.max_price_cents:
        d.reason = "price_out_of_band"
        return d
    if spread > CFG.max_spread_cents:
        d.reason = "spread_too_wide"
        return d
    th = thesis(game, market, side, ask, model, ladder)
    d.model_prob, d.reason_tag, d.source = th["p"], th["tag"], th["source"]
    if th["reject"]:
        d.reason = th["reject"]
        return d
    if th["p"] * 100 - ask < CFG.min_disagreement_cents:
        d.reason = "disagreement_too_small"
        return d
    size = _size(ask, ask_size)
    ev = net_ev_cents(th["p"], ask, size, CFG.fee_coefficient)
    d.size, d.raw_ev, d.fee, d.net_ev, d.roi = (
        size, ev["raw_ev_cents"], ev["fee_cents"], ev["net_ev_cents"], ev["expected_roi"]
    )
    if d.net_ev < CFG.min_net_edge_cents:
        d.reason = "edge_too_small"
        return d
    if d.roi < CFG.min_expected_roi:
        d.reason = "roi_too_small"
        return d
    d.accepted, d.reason = True, "edge_ok"
    return d


def evaluate_slate(games: List[MlbGame], markets: List[KalshiSnap]) -> List[Decision]:
    CFG.assert_paper_safe()
    by_id = {g.game_id: g for g in games}
    models = {g.game_id: project_game(g) for g in games}
    totals: Dict[str, List[KalshiSnap]] = {}
    for m in markets:
        if m.kind == "TOTAL" and m.game_id:
            totals.setdefault(m.game_id, []).append(m)
    ladders = {gid: fit_ladder(arr) for gid, arr in totals.items()}

    scored: List[Decision] = []
    for m in markets:
        game = by_id.get(m.game_id or "")
        if not game:
            scored.append(_base(ticker=m.ticker, kind=m.kind, line=m.line, ask_cents=m.yes_ask or 0,
                                reason="unmatched", reason_tag="unmatched", side="YES"))
            continue
        model = models[game.game_id]
        ladder = ladders.get(game.game_id)
        if m.kind == "RFI":
            scored.append(score(game, m, "YES", model, ladder))
            scored.append(score(game, m, "NO", model, ladder))
        elif m.kind == "TOTAL" and m.line is not None:
            scored.append(score(game, m, "YES", model, ladder))
            scored.append(score(game, m, "NO", model, ladder))

    ranked = sorted(scored, key=lambda d: d.net_ev, reverse=True)
    daily, seen, per_game = 0, set(), {}
    final = {}
    for d in ranked:
        key = f"{d.ticker}:{d.side}"
        if not d.accepted:
            final.setdefault(key, d)
            continue
        if d.ticker in seen:
            d.accepted, d.reason = False, "duplicate_ticker"
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
