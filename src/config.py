from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    d = datetime(year, month, 1)
    first_sun = 1 + (6 - d.weekday()) % 7
    return datetime(year, month, first_sun + 7 * (n - 1))


class Eastern(tzinfo):
    """US Eastern with DST if zoneinfo/tzdata is missing."""

    def utcoffset(self, dt):
        return timedelta(hours=-4 if self._is_dst(dt) else -5)

    def dst(self, dt):
        return timedelta(hours=1) if self._is_dst(dt) else timedelta(0)

    def tzname(self, dt):
        return "EDT" if self._is_dst(dt) else "EST"

    def _is_dst(self, dt) -> bool:
        if dt is None:
            return False
        naive = dt.replace(tzinfo=None)
        start = _nth_sunday(naive.year, 3, 2).replace(hour=2)
        end = _nth_sunday(naive.year, 11, 1).replace(hour=2)
        return start <= naive < end


try:
    from zoneinfo import ZoneInfo

    try:
        ET = ZoneInfo("America/New_York")
    except Exception:
        ET = Eastern()
except Exception:
    ET = Eastern()


def now_et() -> datetime:
    return datetime.now(ET)

@dataclass(frozen=True)
class BotConfig:
    paper_mode: bool = True
    dry_run: bool = True
    min_net_edge_cents: float = 6.0
    min_expected_roi: float = 0.10
    min_disagreement_cents: float = 7.0
    min_price_cents: float = 28.0
    max_price_cents: float = 72.0
    max_spread_cents: float = 5.0
    min_ask_size: float = 1.0
    paper_bankroll: float = 10_000.0
    risk_per_trade_pct: float = 0.25
    max_contracts_per_trade: int = 10
    max_positions_per_game: int = 1
    max_daily_positions: int = 4
    min_minutes_to_pitch: float = 25.0
    max_hours_to_pitch: float = 16.0
    weather_max_minutes: float = 150.0
    require_half_point_totals: bool = True
    fee_coefficient: float = 0.07
    league_f1_lambda: float = 0.48
    league_rpg: float = 4.45
    shrink_weight: float = 0.50
    match_window_hours: float = 6.0
    ladder_min_points: int = 3
    max_quote_age_sec: float = 180.0
    max_page_latency_sec: float = 5.0
    exec_latency_sec: float = 1.0
    log_dir: Path = ROOT / "logs"
    data_dir: Path = ROOT / "data"

    def assert_paper_safe(self) -> None:
        if not self.paper_mode or not self.dry_run:
            raise RuntimeError("live mode is blocked — this package is paper-only")


CFG = BotConfig()
OPEN_STATUSES = frozenset({"open", "active"})
