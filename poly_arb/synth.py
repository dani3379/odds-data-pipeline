"""Synthetic Match generator - lets you run the full engine with NO network/keys.

It builds matches where, by construction:
  * the sharp fair prob is a random walk converging to a 'true' probability,
  * the outcome is drawn from that true prob (so calibration should look good),
  * Polymarket price LAGS the sharp move by `lag` steps and slightly UNDERPRICES
    YES (so a positive edge + a detectable lead-lag exist).

If the engine is correct, `run.py demo` should show: good calibration, positive
mean edge/CLV, and best_lag_steps > 0. This is a self-test, not a real result.
"""
from __future__ import annotations

import numpy as np
from datetime import datetime, timedelta, timezone

from .config import Settings
from .util import iso

# Fixed scenario time keeps seeded demo inputs and bootstrap groups reproducible.
REFERENCE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _clip(x, lo=0.02, hi=0.98):
    return float(min(max(x, lo), hi))


def make_match(i: int, rng: np.random.Generator, s: Settings) -> dict:
    n = int(s.lookback_hours * 60 / s.grid_minutes) + 1
    true_p = float(rng.uniform(0.2, 0.8))
    lag = 1                                  # PM trails sharp by one grid step
    mispricing = float(rng.uniform(-0.01, 0.05))   # usually PM underprices YES -> edge

    fair, val = [], _clip(true_p + rng.normal(0, 0.08))
    for _ in range(n):
        val = _clip(val + (true_p - val) * 0.15 + rng.normal(0, 0.01))
        fair.append(val)
    pm = [_clip(fair[max(0, t - lag)] - mispricing + rng.normal(0, 0.01)) for t in range(n)]

    closing_fair = fair[-1]
    resolved_yes = bool(rng.random() < closing_fair)
    ko = REFERENCE_TIME - timedelta(days=int(rng.integers(1, 40)))

    timeline = []
    for t in range(n):
        mins = (n - 1 - t) * s.grid_minutes
        row_time = ko - timedelta(minutes=mins)
        f = fair[t]
        timeline.append({
            "t": iso(row_time), "mins_to_ko": float(mins),
            "fair_yes": round(f, 4), "pm_price": round(pm[t], 4),
            "p_home": round(f, 4), "p_draw": round((1 - f) * 0.4, 4),
            "p_away": round((1 - f) * 0.6, 4),
        })

    week = ko.isocalendar()
    return {
        "match_id": f"SYNTH-{i:03d}",
        "league": "synthetic",
        "home": f"Home{i}", "away": f"Away{i}",
        "kickoff_utc": iso(ko),
        "match_week": f"{week.year}-W{week.week}",     # bootstrap cluster key
        "yes_outcome": "home",
        "question": f"Will Home{i} win?",
        "condition_id": f"0xsynth{i}", "token_yes": f"tok{i}",
        "resolved_yes": resolved_yes,
        "timeline": timeline,
    }


def make_dataset(n: int = 200, seed: int = 7, s: Settings | None = None) -> list[dict]:
    s = s or Settings()
    rng = np.random.default_rng(seed)
    return [make_match(i, rng, s) for i in range(n)]
