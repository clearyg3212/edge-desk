"""Paper-only scan. Never sends an order to Kalshi."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter

from datetime import datetime, timedelta, timezone

from .config import CFG
from .eligibility import REASON_LABEL
from .engine import evaluate_slate
from .ledger import load_tickets, paper_fill, save_tickets, settle
from .lock import DataLock
from .quotes import append_quotes, label_finals
from .scan import confirm_paper, run_scan
from .types import Decision, KalshiSnap, MlbGame, Pitcher, Weather


def _soon() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _synthetic_paths() -> None:
    """Engine must exercise reject/accept without a network."""
    CFG.assert_paper_safe()
    game = MlbGame(
        game_pk=1,
        game_id="2026-08-29-BOS-NYY-G1",
        official_date="2026-08-29",
        commence_iso=_soon(),
        away_canon="BOS",
        home_canon="NYY",
        away_name="Boston",
        home_name="Yankees",
        venue="Yankee Stadium",
        game_number=1,
        phase="pregame",
        detailed_state="Scheduled",
        away_pitcher=Pitcher(1, "Ace A", 2.10, 11.0, 2.0, 80),
        home_pitcher=Pitcher(2, "Ace B", 2.40, 10.5, 2.1, 90),
        weather=Weather("Clear", 72, 4, "0 mph, None", False),
    )
    cheap = KalshiSnap(
        ticker="KXMLBRFI-99AUG292315BOSNYY",
        title="RFI",
        event_ticker="e",
        series="KXMLBRFI",
        kind="RFI",
        line=0.5,
        yes_bid=30,
        yes_ask=32,
        no_bid=66,
        no_ask=68,
        yes_ask_size=20,
        no_ask_size=20,
        status="open",
        game_id=game.game_id,
    )
    rich = KalshiSnap(
        ticker="KXMLBRFI-99AUG292315BOSNYY2",
        title="RFI",
        event_ticker="e",
        series="KXMLBRFI",
        kind="RFI",
        line=0.5,
        yes_bid=48,
        yes_ask=50,
        no_bid=48,
        no_ask=50,
        yes_ask_size=20,
        no_ask_size=20,
        status="open",
        game_id=game.game_id,
    )
    d_cheap = evaluate_slate([game], [cheap])
    d_rich = evaluate_slate([game], [rich])
    print("[synthetic] two-ace YRFI at 32¢ →", [x.reason for x in d_cheap if x.side == "YES"])
    print("[synthetic] two-ace YRFI at 50¢ →", [x.reason for x in d_rich if x.side == "YES"])


def _print_board(decisions: list[Decision], games: list[MlbGame]) -> None:
    by = {g.game_id: g for g in games}
    accepts = [d for d in decisions if d.accepted]
    rejects = Counter(d.reason for d in decisions if not d.accepted)
    print(f"\n{len(games)} games · {len(decisions)} sides · {len(accepts)} qualify\n")
    if not accepts:
        print("No thesis cleared. Empty is the profit.\n")
    for d in accepts:
        g = by.get(d.game_id)
        vs = f"{g.away_canon}@{g.home_canon}" if g else d.game_id
        print(
            f"  PAPER  {vs:12}  {d.side:3} {d.kind:5}  "
            f"ask {d.ask_cents:.0f}¢  p {d.model_prob*100:.1f}%  "
            f"EV {d.net_ev:.1f}¢  n={d.size}  {d.reason_tag}"
        )
    print("\nreject tape")
    for reason, n in rejects.most_common():
        print(f"  {REASON_LABEL.get(reason, reason):20} {n}")


def _log_decisions(decisions: list[Decision]) -> None:
    CFG.log_dir.mkdir(parents=True, exist_ok=True)
    path = CFG.log_dir / "decisions.jsonl"
    with path.open("a", encoding="utf-8") as f:
        for d in decisions:
            f.write(json.dumps(d.__dict__) + "\n")


def _one_scan(no_paper: bool) -> int:
    print("\nscanning MLB + Kalshi …")
    with DataLock(CFG.data_dir / "bot.lock"):
        tickets = load_tickets()
        scan = run_scan(existing_tickets=tickets)
        for w in scan["warnings"]:
            print("warn:", w)
        if not scan.get("kalshi_ok"):
            print("KALSHI FEED INVALID — not a quiet night. no tickets.")
        decisions, games = scan["decisions"], scan["games"]
        _print_board(decisions, games)
        _log_decisions(decisions)
        nq = append_quotes(decisions, games)
        nl = label_finals(games)

        settle(tickets, games)
        if not no_paper and scan.get("kalshi_ok"):
            by = {g.game_id: g for g in games}
            filled = 0
            for d in decisions:
                g = by.get(d.game_id)
                if not g or not d.accepted:
                    continue
                d2 = confirm_paper(d, g)
                if g and paper_fill(d2, g, tickets):
                    filled += 1
            print(f"\npapered {filled} new ticket(s)")
        elif not scan.get("kalshi_ok"):
            print("\npapered 0 (feed invalid)")
        save_tickets(tickets)
        settled = [t for t in tickets if t.status == "settled"]
        pnl = sum(t.pnl_cents or 0 for t in settled)
        print(f"blotter  open={sum(1 for t in tickets if t.status=='open')}  "
              f"settled={len(settled)}  P&L={pnl/100:.2f} USD")
        print(f"quotes +{nq}  labels +{nl}")
        print(f"log    → {CFG.data_dir / 'quotes.jsonl'}")
        print(f"labels → {CFG.data_dir / 'outcomes.jsonl'}")
        print(f"book   → {CFG.data_dir / 'tickets.jsonl'}")
        print("report → python -m src.report")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="EDGE DESK paper bot — never places Kalshi orders")
    p.add_argument("--once", action="store_true", help="one scan (default)")
    p.add_argument("--loop", type=int, metavar="MIN", default=0,
                   help="rescan every MIN minutes (paper log). Ctrl+C to stop.")
    p.add_argument("--synthetic-only", action="store_true")
    p.add_argument("--no-paper", action="store_true", help="scan but do not write tickets")
    args = p.parse_args(argv)

    print("EDGE DESK  ·  paper only  ·  no live orders")
    CFG.assert_paper_safe()
    _synthetic_paths()
    if args.synthetic_only:
        return 0

    if args.loop and args.loop > 0:
        mins = max(10, args.loop)
        print(f"logging every {mins} min. leave this window open.")
        while True:
            _one_scan(args.no_paper)
            print(f"\nsleeping {mins} min …")
            time.sleep(mins * 60)
    return _one_scan(args.no_paper)


if __name__ == "__main__":
    sys.exit(main())
