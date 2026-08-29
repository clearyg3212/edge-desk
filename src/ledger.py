import json
import os
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .config import CFG
from .fees import kalshi_taker_fee_cents, realized_pnl_cents
from .types import Decision, MlbGame


@dataclass
class Ticket:
    id: str
    opened_at: str
    ticker: str
    game_id: str
    label: str
    kind: str
    side: str
    line: Optional[float]
    ask_cents: float
    model_prob: float
    net_ev: float
    size: int
    reason_tag: str
    status: str = "open"
    outcome: Optional[str] = None
    pnl_cents: Optional[float] = None
    brier: Optional[float] = None
    fee_cents: float = 0.0
    quoted_at: Optional[str] = None
    observed_at: Optional[str] = None


def _path() -> Path:
    CFG.data_dir.mkdir(parents=True, exist_ok=True)
    return CFG.data_dir / "tickets.jsonl"


def load_tickets() -> List[Ticket]:
    p = _path()
    if not p.exists():
        return []
    known = {f.name for f in fields(Ticket)}
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        out.append(Ticket(**{k: v for k, v in raw.items() if k in known}))
    return out


def save_tickets(tickets: List[Ticket]) -> None:
    """Atomic replace so a crash cannot truncate the blotter."""
    p = _path()
    tmp = p.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for t in tickets:
            f.write(json.dumps(asdict(t)) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def paper_fill(d: Decision, game: MlbGame, tickets: List[Ticket]) -> Optional[Ticket]:
    if not d.accepted:
        return None
    tid = f"{d.ticker}:{d.side}:{d.game_id}"
    if any(t.id == tid for t in tickets):
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    todays = [t for t in tickets if t.status != "void" and t.opened_at[:10] == today]
    if len(todays) >= CFG.max_daily_positions:
        return None
    if sum(1 for t in todays if t.game_id == d.game_id) >= CFG.max_positions_per_game:
        return None
    vs = f"{game.away_canon}@{game.home_canon}"
    if d.kind == "RFI":
        mkt = "YRFI" if d.side == "YES" else "NRFI"
    else:
        mkt = f"{'O' if d.side == 'YES' else 'U'}{d.line}"
    fee = d.fee_total or kalshi_taker_fee_cents(d.ask_cents, d.size, CFG.fee_coefficient)
    t = Ticket(
        id=tid,
        opened_at=datetime.now(timezone.utc).isoformat(),
        ticker=d.ticker,
        game_id=d.game_id,
        label=f"{vs} {mkt}",
        kind=d.kind,
        side=d.side,
        line=d.line,
        ask_cents=d.ask_cents,
        model_prob=d.model_prob,
        net_ev=d.net_ev,
        size=d.size,
        reason_tag=d.reason_tag,
        fee_cents=fee,
        quoted_at=d.quoted_at,
        observed_at=d.observed_at,
    )
    tickets.append(t)
    return t


def settle(tickets: List[Ticket], games: List[MlbGame]) -> None:
    by = {g.game_id: g for g in games}
    for t in tickets:
        if t.status != "open":
            continue
        g = by.get(t.game_id)
        if not g:
            continue
        if g.phase == "void":
            t.status, t.pnl_cents = "void", 0
            continue
        if g.phase != "final":
            continue
        yes_won = None
        if t.kind == "RFI" and g.f1_away is not None and g.f1_home is not None:
            yes_won = (g.f1_away + g.f1_home) > 0
        elif t.kind == "TOTAL" and g.total_runs is not None and t.line is not None:
            yes_won = g.total_runs > t.line
        if yes_won is None:
            continue
        we = (t.side == "YES" and yes_won) or (t.side == "NO" and not yes_won)
        t.status = "settled"
        t.outcome = "yes" if yes_won else "no"
        t.pnl_cents = round(realized_pnl_cents(we, t.ask_cents, t.size, CFG.fee_coefficient), 3)
        y = 1.0 if yes_won else 0.0
        p = t.model_prob if t.side == "YES" else 1 - t.model_prob
        t.brier = round((p - y) ** 2, 4)
