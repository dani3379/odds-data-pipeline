"""Link Polymarket markets to odds-api games and build aligned timelines.

The rest of the engine depends only on the Match dict schema produced here:

    Match = {
        match_id, league, home, away, kickoff_utc,
        yes_outcome: "home"|"away"|"draw",   # what the Polymarket YES token means
        question, condition_id, token_yes,
        resolved_yes: bool,                  # did YES happen
        timeline: [ {t, mins_to_ko, fair_yes, pm_price,
                     p_home, p_draw, p_away}, ... ]   # one row per grid step
    }

Linking team names is inherently fuzzy and ALWAYS worth eyeballing once; this
does a best-effort match and you can override via data/processed/manual_links.json.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import timedelta
from typing import Optional

from . import devig
from .oddsapi import consensus_h2h, parse_h2h
from .polymarket import PMMarket
from .util import parse_iso, iso

# minimal alias map; extend as you see mismatches in the link report
ALIASES = {
    "man united": "manchester united", "man utd": "manchester united",
    "man city": "manchester city", "spurs": "tottenham",
    "wolves": "wolverhampton", "newcastle utd": "newcastle",
    "nottm forest": "nottingham forest", "brighton hove albion": "brighton",
}
_STOP = {"fc", "afc", "cf", "sc", "club", "the"}


def normalize_team(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    s = " ".join(w for w in s.split() if w not in _STOP).strip()
    return ALIASES.get(s, s)


def _token_overlap(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def extract_subject(question: str) -> str:
    """Best-effort 'who is this YES market about', from e.g. 'Will Brazil win?'."""
    m = re.search(r"will\s+(.+?)\s+(win|beat|defeat|advance|qualify)", question, re.I)
    return normalize_team(m.group(1)) if m else ""


def sport_for_title(title: str, sport_keys) -> list[str]:
    """Best-guess the-odds-api sport key(s) from a Polymarket title/question."""
    t = (title or "").lower()
    if "world cup" in t or "fifa" in t:
        return [k for k in sport_keys if "world_cup" in k or "fifa" in k] or list(sport_keys)
    if "premier league" in t or "epl" in t:
        return [k for k in sport_keys if "epl" in k] or list(sport_keys)
    return list(sport_keys)


def game_matches_subject(subject: str, game: dict) -> bool:
    h = normalize_team(game.get("home_team", ""))
    a = normalize_team(game.get("away_team", ""))
    return max(_token_overlap(subject, h), _token_overlap(subject, a)) >= 0.5


def link_question_to_game(question: str, games: list[dict]) -> Optional[tuple[dict, str]]:
    """Return (game, side) with side in {home,away}, matching the YES subject team."""
    subject = extract_subject(question)
    if not subject:
        return None
    best, best_score, best_side = None, 0.0, ""
    for g in games:
        home, away = normalize_team(g.get("home_team", "")), normalize_team(g.get("away_team", ""))
        for side, team in (("home", home), ("away", away)):
            sc = _token_overlap(subject, team)
            if sc > best_score:
                best, best_score, best_side = g, sc, side
    if best and best_score >= 0.5:
        return best, best_side
    return None


def link_market_to_game(pm: PMMarket, games: list[dict]) -> Optional[tuple[dict, str]]:
    return link_question_to_game(pm.question, games)


def _asof(series: list[tuple[float, float]], target_unix: float) -> Optional[float]:
    """Last value with timestamp <= target (no look-ahead). series sorted by t."""
    val = None
    for t, v in series:
        if t <= target_unix:
            val = v
        else:
            break
    return val


def build_timeline(yes_outcome: str, sharp_probs_series: list[tuple[float, dict]],
                   pm_price_series: list[tuple[float, float]], kickoff, settings) -> list[dict]:
    """Sample sharp fair-prob and Polymarket price onto a common grid up to kickoff.

    sharp_probs_series: [(unix_t, {'home','draw','away'} fair probs), ...]
    pm_price_series:    [(unix_t, mid_price), ...]
    """
    ko = parse_iso(kickoff) if isinstance(kickoff, str) else kickoff
    ko_u = ko.timestamp()
    start_u = (ko - timedelta(hours=settings.lookback_hours)).timestamp()
    # pre-flatten sharp series for as-of lookup of the chosen outcome
    fair_flat = [(t, p.get(yes_outcome)) for t, p in sharp_probs_series]
    rows, g = [], start_u
    step = settings.grid_minutes * 60
    while g <= ko_u + 1:
        fair_yes = _asof(fair_flat, g)
        pm_price = _asof(pm_price_series, g)
        probs = _asof([(t, p) for t, p in sharp_probs_series], g)
        if fair_yes is not None or pm_price is not None:
            rows.append({
                "t": iso(parse_iso(iso_from_unix(g))),
                "mins_to_ko": round((ko_u - g) / 60.0, 1),
                "fair_yes": fair_yes,
                "pm_price": pm_price,
                "p_home": (probs or {}).get("home"),
                "p_draw": (probs or {}).get("draw"),
                "p_away": (probs or {}).get("away"),
            })
        g += step
    return rows


def iso_from_unix(u: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(u, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_game(games: list[dict], target: dict, target_id) -> Optional[dict]:
    if target_id:
        for g in games:
            if g.get("id") == target_id:
                return g
        return None
    th, ta = target.get("home_team"), target.get("away_team")
    for g in games:
        if g.get("home_team") == th and g.get("away_team") == ta:
            return g
    return None


def build_match_from_bundle(bundle: dict, s) -> Optional[dict]:
    """Pure transform: a fetched raw bundle -> a Match dict (or None if unlinkable).

    bundle = {
        "market": {condition_id, question, token_yes, kickoff_utc, resolved_yes, ...},
        "sport_keys": [...],
        "price_history": [{"t": unix, "p": price}, ...],
        "odds_snapshots": [{"t": iso, "games": [game, ...]}, ...],
    }
    Offline-testable (no network) -- this is the heart of `build`.
    """
    market = bundle.get("market", {})
    snaps = bundle.get("odds_snapshots", [])
    price_history = bundle.get("price_history", [])

    # union of games across snapshots (dedup) for one-time linking
    seen: dict = {}
    for snap in snaps:
        for g in snap.get("games", []):
            gid = g.get("id") or (g.get("home_team"), g.get("away_team"))
            seen[gid] = g
    link = link_question_to_game(market.get("question", ""), list(seen.values()))
    if not link:
        return None
    game, side = link
    game_id = game.get("id")

    # sharp fair-prob series (de-vigged), one point per usable snapshot
    sharp_series: list[tuple[float, dict]] = []
    for snap in snaps:
        g = _find_game(snap.get("games", []), game, game_id)
        if not g:
            continue
        odds = parse_h2h(g, s.sharp_book) or consensus_h2h(g)
        if not odds:
            continue
        probs = devig.devig([odds["home"], odds["draw"], odds["away"]], s.devig_method)
        sharp_series.append((parse_iso(snap["t"]).timestamp(),
                             {"home": probs[0], "draw": probs[1], "away": probs[2]}))
    sharp_series.sort(key=lambda x: x[0])

    pm_series = sorted((float(p["t"]), float(p["p"])) for p in price_history
                       if "t" in p and "p" in p)

    kickoff = market.get("kickoff_utc") or game.get("commence_time")
    if not kickoff:
        return None
    timeline = build_timeline(side, sharp_series, pm_series, kickoff, s)
    if not timeline:
        return None

    ko = parse_iso(kickoff)
    wk = ko.isocalendar()
    return {
        "match_id": market.get("condition_id") or str(game_id) or "?",
        "league": (bundle.get("sport_keys") or ["?"])[0],
        "home": game.get("home_team"), "away": game.get("away_team"),
        "kickoff_utc": iso(ko),
        "match_week": f"{wk.year}-W{wk.week}",
        "yes_outcome": side,
        "question": market.get("question", ""),
        "condition_id": market.get("condition_id"),
        "token_yes": market.get("token_yes"),
        "resolved_yes": market.get("resolved_yes"),
        "timeline": timeline,
    }
