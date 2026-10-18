"""Live Polymarket data: discover upcoming matches, fetch order books + trades.

Uses the shared http_get helper and the computer's standard network configuration.
"""
from __future__ import annotations

import re

from .. import polymarket
from ..util import http_get, parse_iso, utcnow
from .book import OrderBook

CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"
_WIN = re.compile(r"\bwin\b|draw", re.I)


def discover_matches(within_hours=48):
    """Upcoming win/draw match markets kicking off within `within_hours`."""
    now = utcnow().timestamp()
    out = []
    for m in polymarket.search_match_markets(events_status="active"):
        if not _WIN.search(m.question) or not m.kickoff_utc:
            continue
        try:
            ku = parse_iso(m.kickoff_utc).timestamp()
        except Exception:
            continue
        if now < ku <= now + within_hours * 3600:
            out.append({"token": m.token_yes, "condition": m.condition_id,
                        "question": m.question, "kickoff": ku, "label": m.yes_label})
    return out


def fetch_book(token, ts):
    data, _ = http_get(f"{CLOB}/book", {"token_id": token})
    return OrderBook.from_clob(token, ts, data if isinstance(data, dict) else {})


def fetch_trades(condition, token, since_ts=0.0):
    """New trades for `token` (filtered from the match's trade feed) after since_ts.

    Returns (list[{price,size,taker_side,ts}], max_ts).
    """
    data, _ = http_get(f"{DATA}/trades", {"market": condition, "limit": 500})
    rows, mx = [], since_ts
    for t in (data if isinstance(data, list) else []):
        if str(t.get("asset")) != str(token):
            continue
        try:
            ts = float(t.get("timestamp"))
        except (TypeError, ValueError):
            continue
        if ts <= since_ts:
            continue
        rows.append({"price": float(t["price"]), "size": float(t["size"]),
                     "taker_side": str(t.get("side", "")).lower(), "ts": ts})
        mx = max(mx, ts)
    rows.sort(key=lambda r: r["ts"])
    return rows, mx
