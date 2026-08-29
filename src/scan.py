import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import CFG, ET
from .engine import evaluate_slate
from .matching import canon_team, parse_kalshi_ticker, same_matchup
from .parks import DOME_OR_RETRACT
from .types import KalshiSnap, MlbGame, Pitcher, Weather

UA = {"User-Agent": "edge-desk/1.0-paper", "Accept": "application/json"}


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


def _fp(val) -> Optional[float]:
    if val is None:
        return None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    return x if x >= 0 else None


def book_sizes(raw: dict) -> Tuple[Optional[float], Optional[float]]:
    """YES ask size; NO ask size = YES bid size (Kalshi complement)."""
    yes_ask = _fp(raw.get("yes_ask_size_fp"))
    yes_bid = _fp(raw.get("yes_bid_size_fp"))
    no_ask = _fp(raw.get("no_ask_size_fp"))
    if no_ask is None:
        no_ask = yes_bid
    return yes_ask, no_ask


def _stamp_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_updated(raw: dict) -> Optional[str]:
    val = raw.get("updated_time") or raw.get("price_updated_ts") or raw.get("updated_ts")
    if val is None:
        return None
    if isinstance(val, (int, float)):
        ts = float(val)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OSError, ValueError, OverflowError):
            return None
    if isinstance(val, str):
        try:
            datetime.fromisoformat(val.replace("Z", "+00:00"))
            return val
        except ValueError:
            return None
    return None


@dataclass
class FeedResult:
    series: str
    raw: List[dict]
    ok: bool
    error: Optional[str]
    latency_sec: float
    received_at: str


def fetch_series(series: str) -> FeedResult:
    out, cursor = [], None
    total_lat = 0.0
    received = _stamp_iso()
    for _ in range(4):
        u = (
            "https://api.elections.kalshi.com/trade-api/v2/markets"
            f"?series_ticker={series}&status=open&limit=200"
        )
        if cursor:
            u += f"&cursor={cursor}"
        data = None
        err = None
        t0 = time.time()
        for attempt in range(3):
            try:
                data = _get(u)
                err = None
                break
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}"
                if e.code == 429:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                return FeedResult(series, [], False, err, time.time() - t0, _stamp_iso())
            except Exception as e:
                err = str(e) or type(e).__name__
                time.sleep(0.4)
        lat = time.time() - t0
        total_lat += lat
        if not data:
            return FeedResult(series, [], False, err or "empty response", total_lat, _stamp_iso())
        rec = _stamp_iso()
        received = rec
        for m in data.get("markets") or []:
            row = dict(m)
            row["_received_at"] = rec
            row["_page_latency"] = lat
            out.append(row)
        cursor = data.get("cursor") or None
        if not cursor:
            break
        time.sleep(0.25)
    return FeedResult(series, out, True, None, total_lat, received)


def fetch_ticker(ticker: str) -> Optional[dict]:
    u = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
    t0 = time.time()
    data = _get(u, timeout=10)
    rec = _stamp_iso()
    m = data.get("market") or data
    if not isinstance(m, dict) or not m.get("ticker"):
        return None
    row = dict(m)
    row["_received_at"] = rec
    row["_page_latency"] = time.time() - t0
    return row


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
    yes_bid = _to_cents(raw.get("yes_bid_dollars"), raw.get("yes_bid"))
    yes_ask = _to_cents(raw.get("yes_ask_dollars"), raw.get("yes_ask"))
    no_bid = _to_cents(raw.get("no_bid_dollars"), raw.get("no_bid"))
    no_ask = _to_cents(raw.get("no_ask_dollars"), raw.get("no_ask"))
    if no_ask is None and yes_bid is not None:
        no_ask = round(100.0 - yes_bid, 2)
    if no_bid is None and yes_ask is not None:
        no_bid = round(100.0 - yes_ask, 2)
    yes_ask_size, no_ask_size = book_sizes(raw)
    observed = str(raw.get("_received_at") or _stamp_iso())
    quoted = _parse_updated(raw)
    close_time = None
    close_raw = raw.get("close_time") or raw.get("expiration_time")
    if isinstance(close_raw, str):
        close_time = close_raw
    lat = raw.get("_page_latency") or 0.0
    try:
        lat = float(lat)
    except (TypeError, ValueError):
        lat = 0.0
    return KalshiSnap(
        ticker=ticker,
        title=str(raw.get("title") or raw.get("yes_sub_title") or ticker),
        event_ticker=str(raw.get("event_ticker") or ""),
        series=parsed.series,
        kind=parsed.kind,
        line=parsed.line,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
        yes_ask_size=yes_ask_size,
        no_ask_size=no_ask_size,
        status=str(raw.get("status") or ""),
        game_id=game_id,
        quoted_at=quoted,
        observed_at=observed,
        close_time=close_time,
        page_latency_sec=lat,
        trading_active=bool(raw.get("_trading_active", True)),
        result=(str(raw["result"]).lower() if raw.get("result") else None),
    )


def combine_kalshi(rfi: FeedResult, tot: FeedResult, games: List[MlbGame], existing_tickets=None) -> dict:
    warnings = []
    ok = rfi.ok and tot.ok
    if not rfi.ok:
        warnings.append(f"Kalshi {rfi.series} FAILED: {rfi.error}")
    if not tot.ok:
        warnings.append(f"Kalshi {tot.series} FAILED: {tot.error}")
    if ok and not rfi.raw and not tot.raw:
        warnings.append("Kalshi valid-empty: 0 open markets")
    if not ok:
        return {
            "markets": [],
            "decisions": [],
            "kalshi_ok": False,
            "warnings": warnings,
        }
    markets = [m for m in (_link(r, games) for r in (rfi.raw + tot.raw)) if m]
    decisions = evaluate_slate(games, markets, existing_tickets=existing_tickets)
    return {
        "markets": markets,
        "decisions": decisions,
        "kalshi_ok": True,
        "warnings": warnings,
    }


def fetch_exchange_status() -> dict:
    u = "https://api.elections.kalshi.com/trade-api/v2/exchange/status"
    try:
        data = _get(u, timeout=10)
        return {
            "ok": True,
            "trading_active": bool(data.get("trading_active", False)),
            "raw": data,
        }
    except Exception as e:
        return {"ok": False, "trading_active": False, "error": str(e)}


def confirm_paper(d, game: MlbGame, ladder_tickers: Optional[List[str]] = None):
    """Siblings first, target last. Recheck exchange pause. Keep candidate_id."""
    from .engine import _iso_age_sec, score
    from .ladder import fit_ladder
    from .model import project_game

    cid = d.candidate_id
    if CFG.exec_latency_sec > 0:
        time.sleep(CFG.exec_latency_sec)
    ex = fetch_exchange_status()
    if not ex.get("ok") or not ex.get("trading_active"):
        d.accepted = False
        d.reason = "exchange_paused"
        return d
    now = datetime.now(timezone.utc)
    ladder = None
    if d.reason_tag == "ladder_kink":
        sibs = []
        for tkr in ladder_tickers or []:
            if tkr == d.ticker:
                continue
            try:
                sraw = fetch_ticker(tkr)
            except Exception:
                continue
            if not sraw:
                continue
            sm = _link(sraw, [game])
            if not sm:
                continue
            if sm.page_latency_sec and sm.page_latency_sec > CFG.max_page_latency_sec:
                continue
            age = _iso_age_sec(sm.observed_at, now)
            if age is not None and age > CFG.max_quote_age_sec:
                continue
            sibs.append(sm)
        ladder = fit_ladder(sibs, exclude_ticker=d.ticker)
        if not ladder:
            d.accepted = False
            d.reason = "ladder_unconfirmed"
            d.reason_tag = "ladder_kink"
            return d
    try:
        raw = fetch_ticker(d.ticker)
    except Exception:
        d.accepted = False
        d.reason = "stale_quote"
        return d
    if not raw:
        d.accepted = False
        d.reason = "stale_quote"
        return d
    m = _link(raw, [game])
    if not m:
        d.accepted = False
        d.reason = "stale_quote"
        return d
    if not getattr(m, "trading_active", True):
        d.accepted = False
        d.reason = "exchange_paused"
        return d
    fresh = score(game, m, d.side, project_game(game), ladder)
    fresh.candidate_id = cid
    fresh.confirmed_quote = True
    if d.reason_tag == "ladder_kink" and fresh.reason_tag != "ladder_kink":
        fresh.accepted = False
        fresh.reason = "ladder_unconfirmed"
        fresh.reason_tag = "ladder_kink"
        return fresh
    if fresh.accepted and fresh.ask_cents > d.ask_cents + 1:
        fresh.accepted = False
        fresh.reason = "stale_quote"
    return fresh


def run_scan(existing_tickets=None) -> dict:
    warnings = []
    games: List[MlbGame] = []
    mlb_ok = False
    try:
        games = fetch_mlb()
        mlb_ok = True
    except Exception as e:
        warnings.append(f"MLB feed failed: {e}")
    rfi = fetch_series("KXMLBRFI")
    tot = fetch_series("KXMLBTOTAL")
    ex = fetch_exchange_status()
    if not ex["ok"]:
        warnings.append(f"Kalshi exchange status FAILED: {ex.get('error')}")
    elif not ex["trading_active"]:
        warnings.append("Kalshi trading_active=false (exchange pause)")
    live = bool(ex.get("ok") and ex.get("trading_active"))
    for row in list(rfi.raw) + list(tot.raw):
        row["_trading_active"] = live
    packed = combine_kalshi(rfi, tot, games, existing_tickets)
    warnings.extend(packed["warnings"])
    if packed["kalshi_ok"] and not live:
        warnings.append("quotes collected; fills blocked (exchange pause)")
    return {
        "scanned_at": time.time(),
        "games": games,
        "markets": packed["markets"],
        "decisions": packed["decisions"],
        "mlb_ok": mlb_ok,
        "kalshi_ok": packed["kalshi_ok"],
        "trading_active": live,
        "warnings": warnings,
    }
