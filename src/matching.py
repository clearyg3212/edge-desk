import re
from dataclasses import dataclass
from typing import Optional, Tuple

ALIASES = {
    "AZ": "AZ", "ARI": "AZ", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHC": "CHC", "CWS": "CWS", "CHW": "CWS", "CIN": "CIN", "CLE": "CLE",
    "COL": "COL", "DET": "DET", "HOU": "HOU", "KC": "KC", "KCR": "KC",
    "LAA": "LAA", "LAD": "LAD", "MIA": "MIA", "MIL": "MIL", "MIN": "MIN",
    "NYM": "NYM", "NYY": "NYY", "OAK": "ATH", "ATH": "ATH", "PHI": "PHI",
    "PIT": "PIT", "SD": "SD", "SDP": "SD", "SF": "SF", "SFG": "SF",
    "SEA": "SEA", "STL": "STL", "TB": "TB", "TBR": "TB", "TEX": "TEX",
    "TOR": "TOR", "WSH": "WSH", "WAS": "WSH",
}
CODES = sorted(ALIASES, key=len, reverse=True)
MON = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}
TICKER_RE = re.compile(
    r"^(?P<series>KXMLB[A-Z0-9]+)-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})(?P<hhmm>\d{4})"
    r"(?P<teams>[A-Z]+)(?P<dh>\d)?(?:-(?P<strike>\d+(?:\.\d+)?))?$",
    re.I,
)


def canon_team(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    return ALIASES.get(code.strip().upper())


def split_teams(blob: str) -> Tuple[Optional[str], Optional[str]]:
    raw = blob.upper()
    for a in CODES:
        if not raw.startswith(a):
            continue
        rest = raw[len(a):]
        for b in CODES:
            if rest == b:
                return canon_team(a), canon_team(b)
    return None, None


@dataclass
class ParsedTicker:
    ticker: str
    series: str
    kind: str
    away_canon: Optional[str]
    home_canon: Optional[str]
    line: Optional[float]
    game_number: int
    date_key: str
    commence_guess: Optional[str]


def parse_kalshi_ticker(ticker: str, floor_strike: Optional[float] = None) -> Optional[ParsedTicker]:
    m = TICKER_RE.match(ticker.strip())
    if not m:
        return None
    series = m.group("series").upper()
    away, home = split_teams(m.group("teams").upper())
    yy, mon, dd = m.group("yy"), MON.get(m.group("mon").upper(), "01"), m.group("dd")
    date_key = f"20{yy}-{mon}-{dd}"
    hhmm = m.group("hhmm")
    guess = f"{date_key}T{hhmm[:2]}:{hhmm[2:]}:00-04:00"
    dh = int(m.group("dh") or 1)
    kind, line = "UNKNOWN", None
    if series == "KXMLBRFI":
        kind, line = "RFI", 0.5
    elif series == "KXMLBTOTAL":
        kind = "TOTAL"
        if floor_strike is not None:
            line = float(floor_strike)
        elif m.group("strike"):
            suffix = float(m.group("strike"))
            line = suffix - 0.5 if suffix == int(suffix) else suffix
    return ParsedTicker(ticker, series, kind, away, home, line, dh, date_key, guess)


def is_half_point(line: Optional[float]) -> bool:
    if line is None:
        return False
    return abs(line - round(line)) > 1e-9


def same_matchup(a_away: str, a_home: str, b_away: str, b_home: str) -> bool:
    """Exact away/home order. Kalshi ticker is away then home; reversing is a different game."""
    return a_away == b_away and a_home == b_home and a_away != a_home

