"""Adversarial checks. These must pass before you trust a scan."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from .config import CFG
from .fees import kalshi_taker_fee_cents, net_ev_cents, realized_pnl_cents
from .matching import parse_kalshi_ticker, same_matchup
from .engine import evaluate_slate
from .ledger import Ticket, save_tickets, load_tickets, settle
from .types import KalshiSnap, MlbGame, Pitcher, Weather


def _soon() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _game(**kw) -> MlbGame:
    base = dict(
        game_pk=1, game_id="g1", official_date="2026-08-29",
        commence_iso=_soon(),
        away_canon="BOS", home_canon="NYY", away_name="BOS", home_name="NYY",
        venue="Yankee Stadium", game_number=1, phase="pregame", detailed_state="Scheduled",
        away_pitcher=Pitcher(1, "A", 2.1, 11.0, 2.0, 80),
        home_pitcher=Pitcher(2, "B", 2.4, 10.5, 2.1, 90),
        weather=Weather("Clear", 72, 4, "None", False),
    )
    base.update(kw)
    return MlbGame(**base)


def _rfi(ask_yes: float, ticker="KXMLBRFI-99AUG292315BOSNYY", **kw) -> KalshiSnap:
    yes_bid = ask_yes - 2
    m = KalshiSnap(
        ticker=ticker, title="RFI", event_ticker="e", series="KXMLBRFI", kind="RFI",
        line=0.5, yes_bid=yes_bid, yes_ask=ask_yes, no_bid=100 - ask_yes,
        no_ask=100 - yes_bid, yes_ask_size=20, no_ask_size=20, status="open", game_id="g1",
    )
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def test_fee_ceils_on_total():
    total = kalshi_taker_fee_cents(50, contracts=3)
    assert total == 6, total
    one = kalshi_taker_fee_cents(50, contracts=1)
    assert one == 2, one


def test_realized_pnl_subtracts_fee():
    fee = kalshi_taker_fee_cents(32, 10)
    won = realized_pnl_cents(True, 32, 10)
    lost = realized_pnl_cents(False, 32, 10)
    assert won == (100 - 32) * 10 - fee
    assert lost == -32 * 10 - fee
    assert lost < -320


def test_missing_ask_never_inferred():
    g = _game()
    m = _rfi(40)
    m.yes_ask = None
    m.no_ask = None
    d = evaluate_slate([g], [m])
    assert all(x.reason == "missing_price" or not x.accepted for x in d)


def test_zero_depth_not_executable():
    d = evaluate_slate([_game()], [_rfi(32, yes_ask_size=0, no_ask_size=0)])
    yes = [x for x in d if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason == "thin_book"


def test_missing_depth_not_executable():
    d = evaluate_slate([_game()], [_rfi(32, yes_ask_size=None, no_ask_size=None)])
    yes = [x for x in d if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason == "thin_book"


def test_size_capped_to_displayed_depth():
    d = evaluate_slate([_game()], [_rfi(32, yes_ask_size=2, no_ask_size=2)])
    yes = [x for x in d if x.side == "YES"][0]
    if yes.accepted:
        assert yes.size <= 2


def test_negative_spread_rejected():
    d = evaluate_slate([_game()], [_rfi(32, yes_bid=40, yes_ask=32)])
    yes = [x for x in d if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason == "crossed_book"


def test_yes_no_lock_rejected():
    d = evaluate_slate([_game()], [_rfi(32, no_ask=60)])
    yes = [x for x in d if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason == "crossed_book"


def test_closed_market_rejected():
    d = evaluate_slate([_game()], [_rfi(32, status="closed")])
    assert all(x.reason == "closed_market" for x in d)


def test_stale_quote_rejected():
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = evaluate_slate([_game()], [_rfi(32, observed_at=old)])
    yes = [x for x in d if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason == "stale_quote"


def test_ace_tax_rejects_fair_price():
    d = evaluate_slate([_game()], [_rfi(50)])
    yes = [x for x in d if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason in {"no_structural_edge", "edge_too_small", "disagreement_too_small"}


def test_ace_tax_takes_cheap_yes():
    d = evaluate_slate([_game()], [_rfi(32)])
    yes = [x for x in d if x.side == "YES"][0]
    assert yes.accepted, yes
    assert yes.reason_tag == "ace_tax"
    assert yes.size <= CFG.max_contracts_per_trade
    assert yes.observed_at


def test_ace_tax_takes_at_plus_ev_ask():
    yes = [x for x in evaluate_slate([_game()], [_rfi(40)]) if x.side == "YES"][0]
    assert yes.accepted, yes
    assert yes.reason_tag == "ace_tax"


def test_ace_tax_sits_when_kalshi_is_fair():
    yes = [x for x in evaluate_slate([_game()], [_rfi(50)]) if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason in {"no_structural_edge", "disagreement_too_small", "edge_too_small"}


def test_ace_tax_uses_mlb_prior_not_magic_41():
    from .priors import yrfi_p
    p = yrfi_p("two_ace")
    assert 0.45 <= p <= 0.55, p
    yes = [x for x in evaluate_slate([_game()], [_rfi(32)]) if x.side == "YES"][0]
    assert yes.accepted
    assert abs(yes.model_prob - p) < 1e-9
    assert yes.source.startswith("mlb-prior")


def test_live_game_blocked():
    d = evaluate_slate([_game(phase="live")], [_rfi(32)])
    assert all(x.reason == "in_progress" for x in d)


def test_coors_nrfi_veto():
    g = _game(home_canon="COL", venue="Coors Field")
    d = evaluate_slate([g], [_rfi(32)])
    nos = [x for x in d if x.side == "NO"]
    assert nos and nos[0].reason == "coors_nrfi"


def test_ticker_doubleheader():
    p = parse_kalshi_ticker("KXMLBRFI-26AUG291605AZSFG1")
    assert p and p.away_canon == "AZ" and p.home_canon == "SF" and p.game_number == 1
    p2 = parse_kalshi_ticker("KXMLBRFI-26AUG291905AZSFG2")
    assert p2 and p2.game_number == 2


def test_total_half_point():
    p = parse_kalshi_ticker("KXMLBTOTAL-26AUG301920CINCHC-9", floor_strike=8.5)
    assert p and p.kind == "TOTAL" and p.line == 8.5


def test_home_away_not_interchangeable():
    assert same_matchup("BOS", "NYY", "BOS", "NYY")
    assert not same_matchup("BOS", "NYY", "NYY", "BOS")


def test_daily_cap_persists_across_scans():
    existing = [Ticket(
        id="old", opened_at=datetime.now(timezone.utc).isoformat(), ticker="OLD",
        game_id="other", label="x", kind="RFI", side="YES", line=0.5, ask_cents=32,
        model_prob=0.41, net_ev=8, size=5, reason_tag="ace_tax",
    ) for _ in range(4)]
    d = evaluate_slate([_game()], [_rfi(32)], existing_tickets=existing)
    yes = [x for x in d if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason == "daily_limit"


def test_game_cap_persists_across_scans():
    existing = [Ticket(
        id="old", opened_at=datetime.now(timezone.utc).isoformat(), ticker="OLD",
        game_id="g1", label="x", kind="RFI", side="YES", line=0.5, ask_cents=32,
        model_prob=0.41, net_ev=8, size=5, reason_tag="ace_tax",
    )]
    d = evaluate_slate([_game()], [_rfi(32, ticker="KXMLBRFI-99AUG292315BOSNYYX")], existing_tickets=existing)
    yes = [x for x in d if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason == "game_limit"


def test_atomic_ledger_roundtrip():
    from . import config as cfg_mod
    old_dir = Path(cfg_mod.CFG.data_dir)
    with tempfile.TemporaryDirectory() as td:
        object.__setattr__(cfg_mod.CFG, "data_dir", Path(td))
        try:
            t = Ticket(
                id="a", opened_at="2026-08-29T00:00:00+00:00", ticker="T", game_id="g1",
                label="x", kind="RFI", side="YES", line=0.5, ask_cents=32, model_prob=0.41,
                net_ev=8, size=5, reason_tag="ace_tax", fee_cents=2,
            )
            save_tickets([t])
            back = load_tickets()
            assert len(back) == 1 and back[0].fee_cents == 2
            assert (Path(td) / "tickets.jsonl").exists()
            assert not (Path(td) / "tickets.jsonl.tmp").exists()
        finally:
            object.__setattr__(cfg_mod.CFG, "data_dir", old_dir)


def test_settle_fees_in_pnl():
    g = _game(phase="final", f1_away=1, f1_home=0)
    t = Ticket(
        id="a", opened_at="2026-08-29T00:00:00+00:00", ticker="T", game_id="g1",
        label="x", kind="RFI", side="YES", line=0.5, ask_cents=32, model_prob=0.41,
        net_ev=8, size=10, reason_tag="ace_tax",
    )
    settle([t], [g], {"T": {"status": "finalized", "result": "yes"}})
    fee = t.fee_cents or kalshi_taker_fee_cents(32, 10)
    assert t.status == "settled"
    assert t.pnl_cents == (100 - 32) * 10 - fee


def test_quote_log_and_labels():
    from . import config as cfg_mod
    from .quotes import append_quotes, label_finals, load_quotes, load_outcomes
    old_dir = Path(cfg_mod.CFG.data_dir)
    with tempfile.TemporaryDirectory() as td:
        object.__setattr__(cfg_mod.CFG, "data_dir", Path(td))
        try:
            g = _game()
            d = evaluate_slate([g], [_rfi(32)])
            n = append_quotes(d, [g])
            assert n == len(d)
            rows = load_quotes()
            assert rows and rows[0]["away_era"] == 2.1
            assert rows[0]["vs"] == "BOS@NYY"
            labeled = label_finals([_game(phase="final", f1_away=1, f1_home=0)])
            assert labeled == 1
            o = load_outcomes()["g1"]
            assert o.yrfi == 1
        finally:
            object.__setattr__(cfg_mod.CFG, "data_dir", old_dir)


def test_paper_config_locked():
    CFG.assert_paper_safe()
    ev = net_ev_cents(0.41, 32, 1)
    assert ev["net_ev_cents"] > 6


def test_no_ask_size_from_yes_bid():
    from .scan import book_sizes
    y, n = book_sizes({"yes_ask_size_fp": 8, "yes_bid_size_fp": 11})
    assert y == 8 and n == 11


def test_no_side_not_thin_when_yes_bid_size_present():
    from .scan import _link
    raw = {
        "ticker": "KXMLBRFI-26AUG292315BOSNYY",
        "title": "RFI",
        "yes_bid": 30,
        "yes_ask": 32,
        "yes_bid_size_fp": 14,
        "yes_ask_size_fp": 9,
        "status": "open",
        "_received_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_page_latency": 0.2,
    }
    m = _link(raw, [_game()])
    assert m is not None
    assert m.no_ask_size == 14
    assert m.no_ask == 70
    nos = [x for x in evaluate_slate([_game()], [m]) if x.side == "NO"][0]
    assert nos.reason != "thin_book"


def test_sixteen_hour_ceiling_in_eligibility():
    late = (datetime.now(timezone.utc) + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = evaluate_slate([_game(commence_iso=late)], [_rfi(32)])
    assert all(x.reason == "too_early" for x in d)


def test_game_cap_survives_midnight():
    yest = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    existing = [Ticket(
        id="old", opened_at=yest, ticker="OLD", game_id="g1", label="x",
        kind="RFI", side="YES", line=0.5, ask_cents=32, model_prob=0.41,
        net_ev=8, size=5, reason_tag="ace_tax",
    )]
    d = evaluate_slate([_game()], [_rfi(32, ticker="KXMLBRFI-99AUG292315BOSNYYZ")], existing_tickets=existing)
    yes = [x for x in d if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason == "game_limit"


def test_dead_kalshi_is_invalid_not_quiet():
    from .scan import FeedResult, combine_kalshi
    r = combine_kalshi(
        FeedResult("KXMLBRFI", [], False, "timeout", 1.0, "t"),
        FeedResult("KXMLBTOTAL", [], True, None, 0.2, "t"),
        [],
        None,
    )
    assert r["kalshi_ok"] is False
    assert r["markets"] == []
    assert r["decisions"] == []
    assert any("FAILED" in w for w in r["warnings"])


def test_old_updated_time_is_not_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    yes = [x for x in evaluate_slate([_game()], [_rfi(32, quoted_at=old)]) if x.side == "YES"][0]
    assert yes.accepted, yes
    assert yes.reason_tag == "ace_tax"


def test_slow_page_rejected():
    m = _rfi(32)
    m.page_latency_sec = 9.0
    yes = [x for x in evaluate_slate([_game()], [m]) if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason == "stale_quote"


def test_updated_time_iso_does_not_crash():
    from .scan import _parse_updated
    assert _parse_updated({"updated_time": "2026-08-29T21:00:00Z"})
    assert _parse_updated({"updated_time": "nope"}) is None
    assert _parse_updated({"updated_ts": object()}) is None


def test_ladder_ignores_two_points():
    from .thesis import thesis
    from .model import project_game
    g = _game()
    m = _rfi(40)
    m.kind = "TOTAL"
    m.line = 8.5
    th = thesis(g, m, "YES", 40, project_game(g), {"lambda": 8.5, "points": 2})
    assert th["reject"] == "no_structural_edge"


def test_confirm_paper_kills_fill_if_refetch_dies():
    from . import scan as scan_mod
    yes = [x for x in evaluate_slate([_game()], [_rfi(32)]) if x.side == "YES"][0]
    assert yes.accepted
    object.__setattr__(CFG, "exec_latency_sec", 0.0)
    old = scan_mod.fetch_ticker
    scan_mod.fetch_ticker = lambda ticker: None
    try:
        out = scan_mod.confirm_paper(yes, _game())
        assert not out.accepted
        assert out.reason == "stale_quote"
    finally:
        scan_mod.fetch_ticker = old
        object.__setattr__(CFG, "exec_latency_sec", 1.0)


def test_naive_observed_at_does_not_crash():
    naive = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    yes = [x for x in evaluate_slate([_game()], [_rfi(32, observed_at=naive)]) if x.side == "YES"][0]
    assert yes.accepted


def test_exchange_pause_blocks_fill():
    m = _rfi(32)
    m.trading_active = False
    yes = [x for x in evaluate_slate([_game()], [m]) if x.side == "YES"][0]
    assert not yes.accepted
    assert yes.reason == "exchange_paused"


def test_mlb_final_does_not_settle_without_kalshi():
    g = _game(phase="final", f1_away=1, f1_home=0)
    t = Ticket(
        id="a", opened_at="2026-08-29T00:00:00+00:00", ticker="T", game_id="g1",
        label="x", kind="RFI", side="YES", line=0.5, ask_cents=32, model_prob=0.41,
        net_ev=8, size=10, reason_tag="ace_tax", fee_cents=99,
    )
    settle([t], [g])
    assert t.status == "open"


def test_settle_uses_stored_fee():
    t = Ticket(
        id="a", opened_at="2026-08-29T00:00:00+00:00", ticker="T", game_id="g1",
        label="x", kind="RFI", side="YES", line=0.5, ask_cents=32, model_prob=0.41,
        net_ev=8, size=10, reason_tag="ace_tax", fee_cents=99,
    )
    settle([t], [_game()], {"T": {"status": "finalized", "result": "yes"}})
    assert t.status == "settled"
    assert t.pnl_cents == (100 - 32) * 10 - 99


def test_duplicate_ticker_rows_do_not_kill_accept():
    a = _rfi(32)
    b = _rfi(32)
    b.yes_ask = 32
    d = evaluate_slate([_game()], [a, b])
    yes = [x for x in d if x.side == "YES"]
    assert sum(1 for x in yes if x.accepted) == 1


def test_ladder_rejects_duplicate_strikes():
    from .ladder import fit_ladder
    m = _rfi(40)
    m.kind = "TOTAL"
    m.line = 8.5
    m.yes_bid, m.yes_ask = 48, 52
    assert fit_ladder([m, m, m]) is None


def test_report_yes_only_eligible():
    from .report import _yes_last_eligible
    now = datetime.now(timezone.utc)
    commence = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [
        {"event": "candidate_observed", "side": "YES", "ticker": "A", "phase": "pregame",
         "commence": commence, "ts": ts, "tag": "ace_tax"},
        {"event": "candidate_observed", "side": "NO", "ticker": "A", "phase": "pregame",
         "commence": commence, "ts": ts, "tag": "ace_tax"},
        {"event": "execution_attempt", "side": "YES", "ticker": "A", "phase": "pregame",
         "commence": commence, "ts": ts, "tag": "ace_tax"},
    ]
    last = _yes_last_eligible(rows)
    assert len(last) == 1 and last[0]["side"] == "YES"


def run() -> None:
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print("ok ", t.__name__)
        except Exception as e:
            failed += 1
            print("FAIL", t.__name__, type(e).__name__, e)
    if failed:
        raise SystemExit(f"{failed} failed")
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    run()
