import math
from typing import Dict


def kalshi_taker_fee_cents(price_cents: float, contracts: int = 1, coefficient: float = 0.07) -> float:
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0.0
    p = price_cents / 100.0
    fee_dollars = coefficient * contracts * p * (1.0 - p)
    if fee_dollars <= 0:
        return 0.0
    cents = math.ceil(fee_dollars * 100.0 - 1e-12)
    return float(max(1, cents))


def net_ev_cents(
    model_prob: float,
    ask_price_cents: float,
    contracts: int = 1,
    fee_coefficient: float = 0.07,
) -> Dict[str, float]:
    invalid = {"raw_ev_cents": -999.0, "fee_cents": 0.0, "net_ev_cents": -999.0, "expected_roi": -999.0}
    if not (0.0 < model_prob < 1.0):
        return dict(invalid)
    if not (0.0 < ask_price_cents < 100.0):
        return dict(invalid)
    raw = model_prob * 100.0 - ask_price_cents
    fee_per = kalshi_taker_fee_cents(ask_price_cents, contracts, fee_coefficient) / max(1, contracts)
    net = raw - fee_per
    roi = net / ask_price_cents if ask_price_cents > 0 else -999.0
    return {
        "raw_ev_cents": round(raw, 3),
        "fee_cents": round(fee_per, 3),
        "net_ev_cents": round(net, 3),
        "expected_roi": round(roi, 4),
    }
