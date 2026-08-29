PARK_RUN = {
    "COL": 1.28, "CIN": 1.12, "BOS": 1.10, "PHI": 1.08, "NYY": 1.07,
    "TEX": 1.06, "CHC": 1.05, "BAL": 1.04, "ATL": 1.03, "MIN": 1.02,
    "TOR": 1.01, "HOU": 1.00, "LAA": 1.00, "DET": 0.99, "CWS": 0.99,
    "WSH": 0.98, "NYM": 0.98, "MIL": 0.97, "KC": 0.97, "PIT": 0.96,
    "CLE": 0.96, "TB": 0.95, "MIA": 0.94, "STL": 0.94, "LAD": 0.93,
    "ATH": 0.93, "SEA": 0.91, "SF": 0.90, "SD": 0.88, "AZ": 1.02,
}

DOME_OR_RETRACT = {"TB", "TOR", "MIL", "AZ", "HOU", "TEX", "MIA", "SEA"}


def park_factor(home: str) -> float:
    return PARK_RUN.get(home, 1.0)


def is_coors(home: str, venue: str) -> bool:
    return home == "COL" or "coors" in (venue or "").lower()
