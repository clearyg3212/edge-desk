from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
    log_dir: Path = ROOT / "logs"
    data_dir: Path = ROOT / "data"

    def assert_paper_safe(self) -> None:
        if not self.paper_mode or not self.dry_run:
            raise RuntimeError("live mode is blocked — this package is paper-only")


CFG = BotConfig()
OPEN_STATUSES = frozenset({"open", "active"})
