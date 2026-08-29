"""Training log: every quote (pass or take), then labels when MLB is final."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .config import CFG
from .types import Decision, MlbGame


@dataclass
class QuoteRow:
    ts: str
    ticker: str
    side: str
    kind: str
    line: Optional[float]
    game_id: str
    vs: str
    commence: str
    phase: str
    venue: str
    away_sp: Optional[str]
    home_sp: Optional[str]
    away_era: Optional[float]
    home_era: Optional[float]
    away_ip: Optional[float]
    home_ip: Optional[float]
    temp_f: Optional[float]
    wind_mph: Optional[float]
    ask: float
    spread: float
    ask_size: Optional[float]
    model_p: float
    tag: str
    reason: str
    accepted: bool
    event: str = "candidate_observed"
    candidate_id: str = ""
    orig_ask: Optional[float] = None
    confirmed_ask: Optional[float] = None
    filled: Optional[bool] = None
    slippage_cents: Optional[float] = None


@dataclass
class OutcomeRow:
    game_id: str
    labeled_at: str
    phase: str
    f1_away: Optional[float]
    f1_home: Optional[float]
    total_runs: Optional[float]
    yrfi: Optional[int]


def _quotes_path() -> Path:
    CFG.data_dir.mkdir(parents=True, exist_ok=True)
    return CFG.data_dir / "quotes.jsonl"


def _outcomes_path() -> Path:
    CFG.data_dir.mkdir(parents=True, exist_ok=True)
    return CFG.data_dir / "outcomes.jsonl"


def append_quotes(decisions: Iterable[Decision], games: Iterable[MlbGame]) -> int:
    by = {g.game_id: g for g in games}
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    with _quotes_path().open("a", encoding="utf-8") as f:
        for d in decisions:
            g = by.get(d.game_id)
            if not g:
                continue
            row = QuoteRow(
                ts=ts,
                ticker=d.ticker,
                side=d.side,
                kind=d.kind,
                line=d.line,
                game_id=d.game_id,
                vs=f"{g.away_canon}@{g.home_canon}",
                commence=g.commence_iso,
                phase=g.phase,
                venue=g.venue,
                away_sp=g.away_pitcher.name,
                home_sp=g.home_pitcher.name,
                away_era=g.away_pitcher.era,
                home_era=g.home_pitcher.era,
                away_ip=g.away_pitcher.ip,
                home_ip=g.home_pitcher.ip,
                temp_f=g.weather.temp_f,
                wind_mph=g.weather.wind_mph,
                ask=d.ask_cents,
                spread=d.spread_cents,
                ask_size=d.ask_size,
                model_p=d.model_prob,
                tag=d.reason_tag,
                reason=d.reason,
                accepted=d.accepted,
                event="candidate_observed",
                candidate_id=d.candidate_id,
                orig_ask=d.ask_cents,
            )
            f.write(json.dumps(asdict(row)) + "\n")
            n += 1
        f.flush()
        os.fsync(f.fileno())
    return n


def load_outcomes() -> Dict[str, OutcomeRow]:
    p = _outcomes_path()
    if not p.exists():
        return {}
    known = {f.name for f in fields(OutcomeRow)}
    out: Dict[str, OutcomeRow] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        row = OutcomeRow(**{k: v for k, v in raw.items() if k in known})
        out[row.game_id] = row
    return out


def save_outcomes(rows: Dict[str, OutcomeRow]) -> None:
    p = _outcomes_path()
    tmp = p.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows.values():
            f.write(json.dumps(asdict(row)) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def label_finals(games: Iterable[MlbGame]) -> int:
    rows = load_outcomes()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    added = 0
    for g in games:
        if g.phase not in ("final", "void"):
            continue
        yrfi = None
        if g.f1_away is not None and g.f1_home is not None:
            yrfi = 1 if (g.f1_away + g.f1_home) > 0 else 0
        prev = rows.get(g.game_id)
        nxt = OutcomeRow(
            game_id=g.game_id,
            labeled_at=now,
            phase=g.phase,
            f1_away=g.f1_away,
            f1_home=g.f1_home,
            total_runs=g.total_runs,
            yrfi=yrfi,
        )
        if prev is None or (
            prev.phase,
            prev.f1_away,
            prev.f1_home,
            prev.total_runs,
            prev.yrfi,
        ) != (nxt.phase, nxt.f1_away, nxt.f1_home, nxt.total_runs, nxt.yrfi):
            rows[g.game_id] = nxt
            added += 1
    save_outcomes(rows)
    return added


def load_quotes() -> List[dict]:
    p = _quotes_path()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_execution(original: Decision, confirmed: Decision, game: MlbGame, filled: bool) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cid = original.candidate_id or confirmed.candidate_id
    row = QuoteRow(
        ts=ts,
        ticker=original.ticker,
        side=original.side,
        kind=original.kind,
        line=original.line,
        game_id=original.game_id,
        vs=f"{game.away_canon}@{game.home_canon}",
        commence=game.commence_iso,
        phase=game.phase,
        venue=game.venue,
        away_sp=game.away_pitcher.name,
        home_sp=game.home_pitcher.name,
        away_era=game.away_pitcher.era,
        home_era=game.home_pitcher.era,
        away_ip=game.away_pitcher.ip,
        home_ip=game.home_pitcher.ip,
        temp_f=game.weather.temp_f,
        wind_mph=game.weather.wind_mph,
        ask=confirmed.ask_cents,
        spread=confirmed.spread_cents,
        ask_size=confirmed.ask_size,
        model_p=confirmed.model_prob,
        tag=confirmed.reason_tag,
        reason=confirmed.reason,
        accepted=confirmed.accepted,
        event="execution_attempt",
        candidate_id=cid,
        orig_ask=original.ask_cents,
        confirmed_ask=confirmed.ask_cents,
        filled=filled,
        slippage_cents=round(confirmed.ask_cents - original.ask_cents, 3),
    )
    with _quotes_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(row)) + "\n")
        f.flush()
        os.fsync(f.fileno())

