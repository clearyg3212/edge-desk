import math
from typing import List, Tuple

from .config import CFG
from .parks import park_factor
from .types import MlbGame, ModelEstimate, Pitcher, Weather


def _clamp(n: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, n))


def _shrink(p: float, weight: float = CFG.shrink_weight) -> float:
    return _clamp(0.5 + (p - 0.5) * weight, 0.08, 0.92)


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_cdf(k_inclusive: int, lam: float) -> float:
    return min(1.0, sum(poisson_pmf(i, lam) for i in range(k_inclusive + 1)))


def _weather(wx: Weather, home: str) -> Tuple[float, float, List[str]]:
    notes: List[str] = []
    if wx.indoor:
        return 1.0, 1.0, ["indoor"]
    totals = f1 = 1.0
    wind = wx.wind_mph or 0.0
    direction = (wx.wind_dir or "").lower()
    out = "out" in direction
    inn = "in" in direction and not out
    if wind >= 20 and out:
        totals, f1, notes = totals * 1.12, f1 * 1.08, notes + ["wind-out-20"]
    elif wind >= 15 and out:
        totals, f1, notes = totals * 1.06, f1 * 1.04, notes + ["wind-out"]
    elif wind >= 20 and inn:
        totals, f1, notes = totals * 0.90, f1 * 0.92, notes + ["wind-in-20"]
    elif wind >= 15 and inn:
        totals, f1, notes = totals * 0.95, f1 * 0.96, notes + ["wind-in"]
    temp = wx.temp_f
    if temp is not None and temp < 45:
        totals, f1, notes = totals * 0.90, f1 * 0.92, notes + ["cold"]
    elif temp is not None and temp < 50:
        totals, f1, notes = totals * 0.95, f1 * 0.96, notes + ["cool"]
    elif temp is not None and temp > 90:
        totals, f1, notes = totals * 1.04, f1 * 1.03, notes + ["hot"]
    if home in {"CHC", "BOS", "SF"} and wind >= 10:
        notes.append("wind-park")
    return totals, f1, notes


def _pitcher(p: Pitcher) -> Tuple[float, List[str]]:
    notes: List[str] = []
    if p.era is None:
        return 1.0, ["avg-pitcher"]
    idx = _clamp(p.era / 4.2, 0.55, 1.6)
    if p.k9 is not None:
        idx *= 1 - 0.07 * _clamp((p.k9 - 8.2) / 4, -1, 1)
    if p.bb9 is not None:
        idx *= 1 + 0.07 * _clamp((p.bb9 - 3.1) / 2.2, -1, 1)
    idx = _clamp(idx, 0.5, 1.7)
    if p.era < 3.2:
        notes.append("ace")
    if p.era > 5.0:
        notes.append("soft-arm")
    return idx, notes


def project_game(game: MlbGame) -> ModelEstimate:
    park = park_factor(game.home_canon)
    tot_m, f1_m, wx_notes = _weather(game.weather, game.home_canon)
    away_idx, away_n = _pitcher(game.home_pitcher)
    home_idx, home_n = _pitcher(game.away_pitcher)
    lam_f1 = CFG.league_f1_lambda * away_idx * park * f1_m + CFG.league_f1_lambda * home_idx * park * f1_m * 1.03
    nrfi = math.exp(-lam_f1)
    yrfi = 1.0 - nrfi
    lam_g = CFG.league_rpg * away_idx * park * tot_m + CFG.league_rpg * home_idx * park * tot_m * 1.04
    notes = wx_notes + [f"homeSP:{n}" for n in away_n] + [f"awaySP:{n}" for n in home_n]
    notes += [f"park:{park:.2f}", f"λF1:{lam_f1:.2f}", f"λG:{lam_g:.1f}"]

    def over_prob(line: float) -> float:
        return _shrink(1.0 - poisson_cdf(math.floor(line), lam_g))

    return ModelEstimate(_shrink(yrfi), _shrink(nrfi), lam_f1, lam_g, notes, over_prob)
