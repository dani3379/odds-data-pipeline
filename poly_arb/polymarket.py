"""Polymarket data (free, no key): market discovery + historical price/trades.

NOTE: field names from the Gamma API can drift. This layer is defensive and
logs what it finds; the rest of the package depends only on the PMMarket
dataclass below, so API drift is contained here. Verify a provider's current
response schema before adapting _parse_market for a new dataset.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config
from .util import cached_get, http_get, log, parse_iso

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"


@dataclass
class PMMarket:
    condition_id: str
    question: str
    event_title: str
    token_yes: str                 # CLOB token id for the YES outcome
    token_no: Optional[str]
    yes_label: str                 # what "YES" means, e.g. "Brazil"
    kickoff_utc: Optional[str]     # ISO; market/game start
    closed: bool
    resolved_yes: Optional[bool]   # True/False once settled, else None

    def to_dict(self) -> dict:
        return asdict(self)


def _as_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return [v]
    return []


def _parse_market(m: dict, event_title: str) -> Optional[PMMarket]:
    tokens = _as_list(m.get("clobTokenIds"))
    outcomes = _as_list(m.get("outcomes"))
    if not tokens:
        return None
    prices = _as_list(m.get("outcomePrices"))
    resolved = None
    if m.get("closed") and prices:
        try:
            resolved = float(prices[0]) > 0.5      # outcomes[0]==YES convention
        except (TypeError, ValueError):
            resolved = None
    # On match markets, groupItemTitle is the team/outcome ("Spain"); the bare
    # outcomes are just ["Yes","No"]. Prefer the meaningful label for linking.
    yes_label = m.get("groupItemTitle") or (str(outcomes[0]) if outcomes else "YES")
    return PMMarket(
        condition_id=m.get("conditionId", ""),
        question=m.get("question", "?"),
        event_title=event_title,
        token_yes=str(tokens[0]),
        token_no=str(tokens[1]) if len(tokens) > 1 else None,
        yes_label=yes_label,
        kickoff_utc=m.get("gameStartTime") or m.get("startDate"),
        closed=bool(m.get("closed")),
        resolved_yes=resolved,
    )


# Live per-match markets are titled "TeamA vs. TeamB" and are NOT surfaced by
# searching the competition name -- you must search team names. (Observed live.)
WC_TEAMS = [
    # broadened to cover the 48-team field: one searched team per match is enough
    "USA", "Canada", "Mexico", "Argentina", "Brazil", "France", "England", "Spain",
    "Germany", "Portugal", "Netherlands", "Italy", "Belgium", "Croatia", "Uruguay",
    "Colombia", "Morocco", "Senegal", "Japan", "South Korea", "Australia", "Iran",
    "Saudi Arabia", "Qatar", "Switzerland", "Denmark", "Poland", "Serbia", "Ghana",
    "Cameroon", "Egypt", "Algeria", "Tunisia", "Ecuador", "Paraguay", "Cabo Verde",
    "Norway", "Austria", "New Zealand", "Jordan", "Panama", "Uzbekistan", "DR Congo",
    "Ivory Coast", "Scotland", "Bolivia", "Haiti", "Sweden", "Nigeria", "Peru", "Chile",
]

PL_CLUBS = [
    "Manchester City", "Arsenal", "Liverpool", "Manchester United", "Chelsea",
    "Tottenham", "Newcastle", "Aston Villa", "Brighton", "West Ham",
    "Wolverhampton", "Everton", "Nottingham Forest", "Crystal Palace",
    "Fulham", "Brentford", "Bournemouth",
]


def search_markets(terms: list[str], limit_per_type: int = 25,
                   events_status: str = "all", vs_only: bool = False) -> list[PMMarket]:
    """Find markets via the site search endpoint that powers polymarket.com.

    vs_only=True keeps only "TeamA vs. TeamB" match events (drops outrights).
    """
    found: dict[str, PMMarket] = {}
    for term in terms:
        try:
            data, _ = http_get(f"{GAMMA}/public-search",
                               {"q": term, "limit_per_type": limit_per_type,
                                "events_status": events_status})
        except Exception as e:                       # noqa: BLE001
            log(f"  search '{term}' failed: {e}")
            continue
        events = data.get("events", []) if isinstance(data, dict) else []
        for ev in events:
            title = ev.get("title", "?")
            if vs_only and " vs" not in title.lower():
                continue
            for m in ev.get("markets", []):
                pm = _parse_market(m, title)
                if pm and pm.condition_id:
                    found[pm.condition_id] = pm
    return list(found.values())


def search_match_markets(teams: list[str] = None,
                         events_status: str = "active") -> list[PMMarket]:
    """Per-match markets (the strategy's target), found by team search.

    events_status: "active" = upcoming/live; "all" = include FINISHED games
    (filter `.closed` for backtestable, already-resolved matches).
    """
    teams = teams or (WC_TEAMS + PL_CLUBS)
    found: dict[str, PMMarket] = {}
    for pm in search_markets(teams, limit_per_type=20,
                             events_status=events_status, vs_only=True):
        found[pm.condition_id] = pm
    log(f"  -> {len(found)} per-match markets ({events_status})")
    return list(found.values())


def fetch_price_history(token_id: str, fidelity: int = 1) -> list[dict]:
    """Historical mid/last price series: [{'t': unix, 'p': price}, ...].

    NOTE: this is a single price series, NOT order-book depth. Backtests on it
    are 'tier-1' (price gap); fills are modelled with an assumed spread.
    """
    cache = config.RAW / "polymarket" / f"prices_{token_id}.json"
    data = cached_get(cache, f"{CLOB}/prices-history",
                      {"market": token_id, "interval": "max", "fidelity": fidelity})
    return data.get("history", []) if isinstance(data, dict) else []


def fetch_trades(condition_id: str, limit: int = 1000) -> list[dict]:
    """Historical executed trades (tick level). Real liquidity evidence."""
    cache = config.RAW / "polymarket" / f"trades_{condition_id}.json"
    data = cached_get(cache, f"{DATA}/trades",
                      {"market": condition_id, "limit": limit})
    return data if isinstance(data, list) else []


def save_markets(markets: list[PMMarket], path: Path) -> None:
    from .util import save_json
    save_json(path, [m.to_dict() for m in markets])
