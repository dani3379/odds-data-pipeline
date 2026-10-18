"""Offline test of the REAL-data build path (no network).

Feeds a hand-made bundle in the exact the-odds-api game shape through
dataset.build_match_from_bundle -> backtest, proving fetch->build->backtest
works before any live data exists.  Run: python tests/test_build.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poly_arb import dataset
from poly_arb.config import Settings
from poly_arb.backtest import simulate_match
from poly_arb.util import parse_iso


KICKOFF = "2026-05-01T16:00:00Z"


def _game():
    return {
        "id": "g1", "sport_key": "soccer_epl", "commence_time": KICKOFF,
        "home_team": "Arsenal", "away_team": "Chelsea",
        "bookmakers": [{"key": "pinnacle", "title": "Pinnacle", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.80},
                {"name": "Chelsea", "price": 4.50},
                {"name": "Draw", "price": 3.60},
            ]}]}],
    }


def _bundle():
    ko = parse_iso(KICKOFF).timestamp()
    return {
        "market": {
            "condition_id": "0xabc", "question": "Will Arsenal win the match?",
            "token_yes": "tokA", "kickoff_utc": KICKOFF, "resolved_yes": True,
        },
        "sport_keys": ["soccer_epl"],
        # Polymarket YES (Arsenal) priced ~0.50, but de-vigged fair is higher -> edge
        "price_history": [{"t": ko - 7200, "p": 0.50}, {"t": ko - 3600, "p": 0.51}],
        "odds_snapshots": [
            {"t": "2026-05-01T14:00:00Z", "games": [_game()]},
            {"t": "2026-05-01T15:00:00Z", "games": [_game()]},
        ],
    }


def test_linking_and_sport_helpers():
    assert dataset.sport_for_title("FIFA World Cup", ["soccer_epl", "soccer_fifa_world_cup"]) \
        == ["soccer_fifa_world_cup"]
    assert dataset.extract_subject("Will Arsenal win the match?") == "arsenal"
    link = dataset.link_question_to_game("Will Arsenal win?", [_game()])
    assert link and link[1] == "home"


def test_build_match_from_bundle():
    s = Settings(lookback_hours=12, grid_minutes=30, devig_method="shin")
    m = dataset.build_match_from_bundle(_bundle(), s)
    assert m is not None
    assert m["home"] == "Arsenal" and m["yes_outcome"] == "home"
    rows = [r for r in m["timeline"] if r["fair_yes"] is not None and r["pm_price"] is not None]
    assert rows, "expected aligned rows with both fair and PM price"
    fair = rows[-1]["fair_yes"]
    assert 0.45 < fair < 0.75, f"Arsenal fair prob looks wrong: {fair}"   # ~0.53 from 1.80


def test_build_to_backtest():
    s = Settings(lookback_hours=12, grid_minutes=30, edge_threshold=0.02,
                 half_spread=0.0, fee=0.0, slippage=0.0)
    m = dataset.build_match_from_bundle(_bundle(), s)
    trades = simulate_match(m, s)
    assert len(trades) == 1
    t = trades[0]
    assert t.won is True and t.pnl > 0     # Arsenal won, bought YES below fair


def test_iter_snapshots_dedupes_coarse_cadence():
    """If the native archive only has a snapshot every 2h, requesting every 30min
    must NOT produce fake fine-grained points -- it must dedupe to the real ones."""
    from datetime import timezone
    from poly_arb import oddsapi
    from poly_arb.util import parse_iso

    def fake_snapshot(sport, when, key, regions, markets="h2h", odds_format="decimal"):
        # native cadence = 2h: floor the requested time to a 2-hour block
        epoch = int(when.timestamp())
        block = (epoch // (2 * 3600)) * (2 * 3600)
        from datetime import datetime
        actual = datetime.fromtimestamp(block, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"timestamp": actual, "previous_timestamp": None, "data": [_game()]}

    orig = oddsapi.historical_snapshot
    oddsapi.historical_snapshot = fake_snapshot
    try:
        s = Settings(lookback_hours=12, snap_minutes=30)   # would be 25 requests
        snaps = oddsapi.iter_snapshots("soccer_epl", parse_iso(KICKOFF), "k", s)
    finally:
        oddsapi.historical_snapshot = orig
    stamps = [x["t"] for x in snaps]
    assert len(stamps) == len(set(stamps)), "duplicates leaked into the progression"
    # 12h window at 2h native cadence -> ~6-7 distinct snapshots, not 25
    assert 5 <= len(stamps) <= 8, f"expected ~6 distinct snapshots, got {len(stamps)}"


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} build-path tests passed.")


if __name__ == "__main__":
    _run()
