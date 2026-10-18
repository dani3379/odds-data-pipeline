"""the-odds-api historical odds (PAID for /historical; free key for /sports).

A single historical call returns ALL games for a sport at one timestamp, so we
iterate timestamps over the pre-match window and cache each snapshot. Cost is
reported from the x-requests-* headers so you always see what you're spending.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import config
from .util import cached_get, http_get, iso, load_json, log, parse_iso, save_json

BASE = "https://api.the-odds-api.com/v4"


def list_sports(key: str) -> list[dict]:
    data, _ = http_get(f"{BASE}/sports/", {"apiKey": key})
    return data if isinstance(data, list) else []


def historical_snapshot(sport: str, when: datetime, key: str,
                        regions: str, markets: str = "h2h",
                        odds_format: str = "decimal") -> dict:
    """One historical snapshot for `sport` at `when`. Cached to disk (=no re-bill)."""
    stamp = iso(when)
    cache = config.RAW / "oddsapi" / f"{sport}_{stamp.replace(':', '')}.json"
    if cache.exists():
        return load_json(cache)
    data, hdrs = http_get(f"{BASE}/historical/sports/{sport}/odds/", {
        "apiKey": key, "regions": regions, "markets": markets,
        "oddsFormat": odds_format, "date": stamp,
    })
    save_json(cache, data)
    log(f"  odds snapshot {sport} @ {stamp}  "
        f"[used={hdrs.get('x-requests-used')} remaining={hdrs.get('x-requests-remaining')}]")
    return data


def _floor_to_grid(dt: datetime, step_minutes: int) -> datetime:
    """Snap a time DOWN to a fixed global grid so overlapping matches share
    snapshot timestamps (and therefore the disk cache / API spend)."""
    epoch = int(dt.timestamp())
    step = step_minutes * 60
    return datetime.fromtimestamp((epoch // step) * step, tz=timezone.utc)


def iter_snapshots(sport: str, kickoff: datetime, key: str, settings) -> list[dict]:
    """Grid-aligned snapshots from (kickoff - lookback) to kickoff.

    Returns [{'t': iso, 'games': [...]}]. Timestamps are floored to the global
    snap grid; identical timestamps across matches reuse the cache (=no re-bill).
    """
    start = _floor_to_grid(kickoff - timedelta(hours=settings.lookback_hours),
                           settings.snap_minutes)
    snaps, t, last_actual = [], start, None
    while t <= kickoff:
        try:
            raw = historical_snapshot(sport, t, key, settings.regions, "h2h",
                                      settings.odds_format)
            # Use the snapshot's REAL timestamp, not the grid time we requested.
            # The endpoint returns the nearest snapshot at/before `date`, so if the
            # native cadence is coarser than snap_minutes we'd get duplicates --
            # dedupe them so the progression reflects only distinct snapshots.
            actual = (raw.get("timestamp") if isinstance(raw, dict) else None) or iso(t)
            if actual != last_actual:
                snaps.append({"t": actual, "games": snapshot_games(raw)})
                last_actual = actual
        except Exception as e:                                   # noqa: BLE001
            log(f"  snapshot failed @ {iso(t)}: {e}")
        t += timedelta(minutes=settings.snap_minutes)
    return snaps


def snapshot_games(snap) -> list[dict]:
    """Historical endpoint nests games under 'data'; live endpoint is a bare list."""
    if isinstance(snap, dict):
        return snap.get("data", []) or []
    return snap if isinstance(snap, list) else []


def probe_cadence(sport: str, key: str, regions: str, date_iso: str,
                  steps: int = 6, markets: str = "h2h",
                  odds_format: str = "decimal") -> dict:
    """MEASURE the native snapshot cadence by walking `previous_timestamp`.

    Costs ~`steps` historical calls (a few credits). This answers the only
    question the free validator can't: is the odds-side PROGRESSION actually
    fine-grained, or does the archive only hold sparse snapshots?
    """
    times, cursor = [], date_iso
    for _ in range(steps + 1):
        if not cursor:
            break
        raw, hdrs = http_get(f"{BASE}/historical/sports/{sport}/odds/", {
            "apiKey": key, "regions": regions, "markets": markets,
            "oddsFormat": odds_format, "date": cursor})
        ts = raw.get("timestamp") if isinstance(raw, dict) else None
        prev = raw.get("previous_timestamp") if isinstance(raw, dict) else None
        log(f"  cadence: ts={ts} games={len(snapshot_games(raw))} "
            f"[remaining={hdrs.get('x-requests-remaining')}]")
        if ts:
            times.append(ts)
        cursor = prev
    parsed = sorted(parse_iso(t) for t in times)
    gaps = [round((b - a).total_seconds() / 60.0, 1) for a, b in zip(parsed, parsed[1:])]
    med = statistics.median(gaps) if gaps else None
    return {
        "n_snapshots": len(parsed),
        "snapshots": [iso(p) for p in parsed],
        "gaps_minutes": gaps,
        "median_gap_min": med,
        "meets_30min": (med is not None and med <= 30),
    }


def parse_h2h(game: dict, book_title: str) -> Optional[dict]:
    """Extract 1X2 decimal odds for one bookmaker.

    Returns {'home','draw','away'} decimal odds, or None if unavailable.
    the-odds-api uses team names for home/away and 'Draw' for the draw.
    """
    home, away = game.get("home_team"), game.get("away_team")
    for bk in game.get("bookmakers", []):
        if bk.get("title") != book_title:
            continue
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            odds = {}
            for oc in mk.get("outcomes", []):
                name, price = oc.get("name"), oc.get("price")
                if name == home:
                    odds["home"] = price
                elif name == away:
                    odds["away"] = price
                elif name and name.lower() == "draw":
                    odds["draw"] = price
            if {"home", "draw", "away"} <= odds.keys():
                return odds
    return None


def consensus_h2h(game: dict) -> Optional[dict]:
    """Average decimal odds across all books (fallback when sharp book absent)."""
    home, away = game.get("home_team"), game.get("away_team")
    acc = {"home": [], "draw": [], "away": []}
    for bk in game.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            for oc in mk.get("outcomes", []):
                name, price = oc.get("name"), oc.get("price")
                if name == home:
                    acc["home"].append(price)
                elif name == away:
                    acc["away"].append(price)
                elif name and name.lower() == "draw":
                    acc["draw"].append(price)
    if all(acc.values()):
        return {k: sum(v) / len(v) for k, v in acc.items()}
    return None
