import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from .config import CFG
from .engine import evaluate_slate
from .matching import canon_team, parse_kalshi_ticker, same_matchup
from .parks import DOME_OR_RETRACT
from .types import KalshiSnap, MlbGame, Pitcher, Weather

UA = {"User-Agent": "edge-desk/1.0-paper", "Accept": "application/json"}
ET = ZoneInfo("America/New_York")


def _get(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _to_cents(*vals) -> Optional[float]:
    for val in vals:
        if val is None:
            continue
        v = float(val)
        if v < 0:
            continue
        if v <= 1:
            return round(v * 100.0, 2)
        if v <= 100:
            return round(v, 2)
    return None


def _parse_ip(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    parts = str(s).split(".")
    try:
        whole = float(parts[0])
    except ValueError:
        return None
    frac = float(parts[1]) / 3.0 if len(parts) > 1 and parts[1] else 0.0
    return whole + frac


def _phase(status: dict) -> str:
    abs_ = status.get("abstractGameState") or ""
    det = (status.get("detailedState") or "").lower()
    if any(x in det for x in ("postpon", "cancel", "suspend")):
        return "void"
    if abs_ == "Final":
        return "final"
    if abs_ == "Live" or "in progress" in det or det == "warmup":
        return "live"
    return "pregame"


def _weather(raw: Optional[dict], home: str) -> Weather:
    raw = raw or {}
    cond = raw.get("condition") or ""
    indoor = home in DOME_OR_RETRACT and ("roof closed" in cond.lower() or "dome" in cond.lower() or cond == "Roof Closed")
    indoor = indoor or "dome" in cond.lower()
    wind = raw.get("wind") or ""
    import re
    m = re.search(r"(\d+)\s*mph", wind, re.I)
    temp = raw.get("temp")
    try:
        temp_f = float(temp) if temp not in (None, "") else None
    except ValueError:
        temp_f = None
    return Weather(cond, temp_f, float(m.group(1)) if m else None, wind, indoor)


def _pitcher_stats(ids: List[int]) -> Dict[int, Pitcher]:
    uniq = [i for i in dict.fromkeys(ids) if i]
    out: Dict[int, Pitcher] = {}
    if not uniq:
        return out
    url = (
        "https://statsapi.mlb.com/api/v1/people?personIds="
        + ",".join(str(i) for i in uniq[:80])
        + "&hydrate=stats(group=[pitching],type=[season])"
    )
    data = _get(url)
    for p in data.get("people") or []:
        pid = int(p["id"])
        splits = ((p.get("stats") or [{}])[0].get("splits") or [{}])
        stat = (splits[0].get("stat") if splits else {}) or {}
        ip = _parse_ip(str(stat.get("inningsPitched") or ""))
        so, bb, era_s = stat.get("strikeOuts"), stat.get("baseOnBalls"), stat.get("era")
        try:
            era = float(era_s) if era_s not in (None, "") else None
        except ValueError:
            era = None
        k9 = (float(so) * 9 / ip) if ip and so is not None and ip > 0 else None
        bb9 = (float(bb) * 9 / ip) if ip and bb is not None and ip > 0 else None
        out[pid] = Pitcher(pid, p.get("fullName"), era, k9, bb9, ip)
    return out


def fetch_mlb() -> List[MlbGame]:
    today = datetime.now(ET)
    d0 = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    d2 = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    url = (
        "https://statsapi.mlb.com/api/v1/schedule?sportId=1"
        f"&startDate={d0}&endDate={d2}&hydrate=probablePitcher,weather,linescore,team"
    )
    data = _get(url)
    raw = []
    for day in data.get("dates") or []:
        raw.extend(day.get("games") or [])
    pids = []
    for g in raw:
        teams = g.get("teams") or {}
        for side in ("away", "home"):
            pid = ((teams.get(side) or {}).get("probablePitcher") or {}).get("id")
            if pid:
                pids.append(int(pid))
    stats = _pitcher_stats(pids)
    games = []
    for g in raw:
        teams = g["teams"]
        away_c = canon_team(teams["away"]["team"].get("abbreviation")) or teams["away"]["team"].get("abbreviation") or "?"
        home_c = canon_team(teams["home"]["team"].get("abbreviation")) or teams["home"]["team"].get("abbreviation") or "?"
        ap, hp = teams["away"].get("probablePitcher") or {}, teams["home"].get("probablePitcher") or {}
        away_p = stats.get(ap["id"], Pitcher(ap.get("id"), ap.get("fullName"))) if ap.get("id") else Pitcher()
        home_p = stats.get(hp["id"], Pitcher(hp.get("id"), hp.get("fullName"))) if hp.get("id") else Pitcher()
        inns = ((g.get("linescore") or {}).get("innings") or [{}])
        i0 = inns[0] if inns else {}
        gn = int(g.get("gameNumber") or 1)
        official = str(g.get("officialDate") or d2)
        aw_score, hm_score = teams["away"].get("score"), teams["home"].get("score")
        total = (float(aw_score) + float(hm_score)) if aw_score is not None and hm_score is not None else None
        games.append(
            MlbGame(
                game_pk=int(g["gamePk"]),
                game_id=f"{official}-{away_c}-{home_c}-G{gn}",
                official_date=official,
                commence_iso=str(g["gameDate"]),
                away_canon=away_c,
                home_canon=home_c,
                away_name=teams["away"]["team"].get("name") or away_c,
                home_name=teams["home"]["team"].get("name") or home_c,
                venue=(g.get("venue") or {}).get("name") or "",
                game_number=gn,
                phase=_phase(g.get("status") or {}),
                detailed_state=(g.get("status") or {}).get("detailedState") or "",
                away_pitcher=away_p,
                home_pitcher=home_p,
                weather=_weather(g.get("weather"), home_c),
                f1_away=(i0.get("away") or {}).get("runs"),
                f1_home=(i0.get("home") or {}).get("runs"),
                total_runs=total,
            )
        )
    return games


def fetch_series(series: str) -> List[dict]:
    out, cursor = [], None
    for _ in range(4):
        u = (
            "https://api.elections.kalshi.com/trade-api/v2/markets"
            f"?series_ticker={series}&status=open&limit=200"
        )
        if cursor:
            u += f"&cursor={cursor}"
        data = None
        for attempt in range(3):
            try:
                data = _get(u)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                raise
            except Exception:
                time.sleep(0.4)
        if not data:
            break
        out.extend(data.get("markets") or [])
        cursor = data.get("cursor") or None
        if not cursor:
            break
        time.sleep(0.25)
    return out


def _link(raw: dict, games: List[MlbGame]) -> Optional[KalshiSnap]:
    ticker = str(raw.get("ticker") or "")
    floor = float(raw["floor_strike"]) if raw.get("floor_strike") is not None else None
    parsed = parse_kalshi_ticker(ticker, floor)
    if not parsed or parsed.kind == "UNKNOWN":
        return None
    game_id = None
    if parsed.away_canon and parsed.home_canon:
        try:
            guess = datetime.fromisoformat(parsed.commence_guess).timestamp() if parsed.commence_guess else None
        except ValueError:
            guess = None
        best, best_dt = None, 1e18
        for g in games:
            if not same_matchup(g.away_canon, g.home_canon, parsed.away_canon, parsed.home_canon):
                continue
            if parsed.game_number != g.game_number:
                continue
            dt = abs(datetime.fromisoformat(g.commence_iso.replace("Z", "+00:00")).timestamp() - guess) if guess else 0
            if dt < best_dt:
                best_dt, best = dt, g
        if best:
            if guess is None:
                if best.official_date == parsed.date_key:
                    game_id = best.game_id
            elif best_dt < CFG.match_window_hours * 3600:
                game_id = best.game_id
    observed = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    quoted = None
    for key in ("price_updated_ts", "last_price_updated_ts", "updated_ts"):
        raw_ts = raw.get(key)
        if raw_ts is None:
            continue
        try:
            ts = float(raw_ts)
            if ts > 1e12:
                ts /= 1000.0
            quoted = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            break
        except (TypeError, ValueError, OSError):
            continue
    close_time = None
    close_raw = raw.get("close_time") or raw.get("expiration_time")
    if isinstance(close_raw, str):
        close_time = close_raw
    return KalshiSnap(
        ticker=ticker,
        title=str(raw.get("title") or raw.get("yes_sub_title") or ticker),
        event_ticker=str(raw.get("event_ticker") or ""),
        series=parsed.series,
        kind=parsed.kind,
        line=parsed.line,
        yes_bid=_to_cents(raw.get("yes_bid_dollars"), raw.get("yes_bid")),
        yes_ask=_to_cents(raw.get("yes_ask_dollars"), raw.get("yes_ask")),
        no_bid=_to_cents(raw.get("no_bid_dollars"), raw.get("no_bid")),
        no_ask=_to_cents(raw.get("no_ask_dollars"), raw.get("no_ask")),
        yes_ask_size=float(raw["yes_ask_size_fp"]) if raw.get("yes_ask_size_fp") is not None else None,
        no_ask_size=float(raw["no_ask_size_fp"]) if raw.get("no_ask_size_fp") is not None else None,
        status=str(raw.get("status") or ""),
        game_id=game_id,
        quoted_at=quoted,
        observed_at=observed,
        close_time=close_time,
    )


def run_scan(existing_tickets=None) -> dict:
    warnings = []
    games: List[MlbGame] = []
    mlb_ok = kalshi_ok = False
    try:
        games = fetch_mlb()
        mlb_ok = True
    except Exception as e:
        warnings.append(f"MLB feed failed: {e}")
    markets: List[KalshiSnap] = []
    try:
        raw = fetch_series("KXMLBRFI") + fetch_series("KXMLBTOTAL")
        markets = [m for m in (_link(r, games) for r in raw) if m]
        kalshi_ok = True
    except Exception as e:
        warnings.append(f"Kalshi feed failed: {e}")
    decisions = evaluate_slate(games, markets, existing_tickets=existing_tickets)
    return {
        "scanned_at": time.time(),
        "games": games,
        "markets": markets,
        "decisions": decisions,
        "mlb_ok": mlb_ok,
        "kalshi_ok": kalshi_ok,
        "warnings": warnings,
    }
