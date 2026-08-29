"""Adversarial checks. These must pass before you trust a scan."""
from datetime import datetime, timedelta, timezone

from .config import CFG
from .fees import kalshi_taker_fee_cents, net_ev_cents
from .matching import parse_kalshi_ticker
from .engine import evaluate_slate
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


def _rfi(ask_yes: float, ticker="KXMLBRFI-99AUG292315BOSNYY") -> KalshiSnap:
    return KalshiSnap(
        ticker=ticker, title="RFI", event_ticker="e", series="KXMLBRFI", kind="RFI",
        line=0.5, yes_bid=ask_yes - 2, yes_ask=ask_yes, no_bid=100 - ask_yes - 4,
        no_ask=100 - ask_yes - 2, yes_ask_size=20, no_ask_size=20, status="open", game_id="g1",
    )


def test_fee_ceils_on_total():
    # 0.07 * 3 * 0.5 * 0.5 = 0.0525 → 5.25 cents → ceil 6 total, 2 per contract
    total = kalshi_taker_fee_cents(50, contracts=3)
    assert total == 6, total
    one = kalshi_taker_fee_cents(50, contracts=1)
    assert one == 2, one


def test_missing_ask_never_inferred():
    g = _game()
    m = _rfi(40)
    m.yes_ask = None
    m.no_ask = None
    d = evaluate_slate([g], [m])
    assert all(x.reason == "missing_price" or not x.accepted for x in d)


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


def test_total_half_point():
    p = parse_kalshi_ticker("KXMLBTOTAL-26AUG301920CINCHC-9", floor_strike=8.5)
    assert p and p.kind == "TOTAL" and p.line == 8.5


def test_paper_config_locked():
    CFG.assert_paper_safe()
    ev = net_ev_cents(0.41, 32, 1)
    assert ev["net_ev_cents"] > 6


def run() -> None:
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print("ok ", t.__name__)
        except Exception as e:
            failed += 1
            print("FAIL", t.__name__, e)
    if failed:
        raise SystemExit(f"{failed} failed")
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    run()
