from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class Pitcher:
    id: Optional[int] = None
    name: Optional[str] = None
    era: Optional[float] = None
    k9: Optional[float] = None
    bb9: Optional[float] = None
    ip: Optional[float] = None


@dataclass
class Weather:
    condition: str = ""
    temp_f: Optional[float] = None
    wind_mph: Optional[float] = None
    wind_dir: str = ""
    indoor: bool = False


@dataclass
class MlbGame:
    game_pk: int
    game_id: str
    official_date: str
    commence_iso: str
    away_canon: str
    home_canon: str
    away_name: str
    home_name: str
    venue: str
    game_number: int
    phase: str
    detailed_state: str
    away_pitcher: Pitcher
    home_pitcher: Pitcher
    weather: Weather
    f1_away: Optional[float] = None
    f1_home: Optional[float] = None
    total_runs: Optional[float] = None


@dataclass
class KalshiSnap:
    ticker: str
    title: str
    event_ticker: str
    series: str
    kind: str
    line: Optional[float]
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    no_bid: Optional[float]
    no_ask: Optional[float]
    yes_ask_size: Optional[float]
    no_ask_size: Optional[float]
    status: str
    game_id: Optional[str]
    quoted_at: Optional[str] = None
    observed_at: Optional[str] = None
    close_time: Optional[str] = None
    page_latency_sec: float = 0.0
    trading_active: bool = True
    result: Optional[str] = None


@dataclass
class ModelEstimate:
    yrfi: float
    nrfi: float
    lambda_f1: float
    lambda_game: float
    notes: List[str]
    over_prob: Callable[[float], float] = field(repr=False)


@dataclass
class Decision:
    ticker: str
    game_id: str
    kind: str
    side: str
    line: Optional[float]
    ask_cents: float
    spread_cents: float
    model_prob: float
    raw_ev: float
    fee: float
    net_ev: float
    roi: float
    size: int
    accepted: bool
    reason: str
    reason_tag: str
    source: str
    fee_total: float = 0.0
    quoted_at: Optional[str] = None
    observed_at: Optional[str] = None
    ask_size: Optional[float] = None
