"""Unit tests for the pure-logic core (no network). Run: python -m pytest -q
or just: python tests/test_core.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poly_arb import devig, stats
from poly_arb.config import Settings
from poly_arb.backtest import simulate_match, _kelly_fraction, _effective_cost


def test_devig_sums_to_one():
    odds = [2.10, 3.40, 3.80]            # a typical 1X2 with vig
    for method in ("multiplicative", "power", "shin"):
        p = devig.devig(odds, method)
        assert abs(sum(p) - 1.0) < 1e-6, method
        assert all(0 < x < 1 for x in p)


def test_devig_removes_overround():
    odds = [2.10, 3.40, 3.80]
    assert devig.booksum(odds) > 1.0          # raw has vig
    # fair probs are each below their raw inverse (vig stripped)
    raw = devig.inverse(odds)
    fair = devig.devig(odds, "shin")
    assert sum(fair) < sum(raw)


def test_effective_cost_and_kelly():
    s = Settings(half_spread=0.01, fee=0.0, slippage=0.0)
    assert abs(_effective_cost(0.50, s) - 0.51) < 1e-9
    # positive edge -> positive fraction, capped
    f = _kelly_fraction(0.60, 0.50, s)
    assert 0 < f <= s.kelly_cap
    # no edge -> zero
    assert _kelly_fraction(0.49, 0.50, s) == 0.0


def test_backtest_settles_correctly():
    s = Settings(edge_threshold=0.03, half_spread=0.0, fee=0.0, slippage=0.0,
                 kelly_fraction=1.0, kelly_cap=1.0, bankroll=100.0)
    # YES truly worth 0.7, priced 0.50 -> edge 0.20; outcome happens -> profit
    match = {
        "match_id": "T1", "league": "x", "resolved_yes": True, "match_week": "w1",
        "timeline": [{"t": "2026-01-01T00:00:00Z", "mins_to_ko": 30,
                      "fair_yes": 0.70, "pm_price": 0.50}],
    }
    trades = simulate_match(match, s)
    assert len(trades) == 1
    t = trades[0]
    assert t.won is True and t.pnl > 0 and t.ret > 0
    # shares = stake/0.50, payoff = shares, pnl = shares - stake = stake
    assert abs(t.pnl - t.stake) < 1e-6


def test_calibration_and_bootstrap():
    # perfectly calibrated synthetic: prob = base rate
    probs = [0.5] * 100
    ys = [1.0] * 50 + [0.0] * 50
    assert abs(stats.brier_binary(probs, ys) - 0.25) < 1e-9
    ci = stats.bootstrap_mean_ci([0.1] * 20, ["a"] * 10 + ["b"] * 10, iters=500)
    assert ci["ci_low"] <= ci["mean"] <= ci["ci_high"]


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")


if __name__ == "__main__":
    _run()
