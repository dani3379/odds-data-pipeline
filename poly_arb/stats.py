"""Validation statistics: calibration, clustered bootstrap, lead-lag.

These are the 'don't fool yourself' checks. Calibration validates the benchmark
before any edge is trusted; the clustered bootstrap gives an honest confidence
interval on returns (bets in the same match-week are correlated); lead-lag tests
your core hypothesis: does Polymarket FOLLOW sharp odds moves, and by how long?
"""
from __future__ import annotations

import numpy as np


def brier_binary(probs, outcomes) -> float:
    p = np.asarray(probs, float)
    y = np.asarray(outcomes, float)
    return float(np.mean((p - y) ** 2))


def reliability_table(probs, outcomes, bins: int = 10) -> list[dict]:
    p = np.asarray(probs, float)
    y = np.asarray(outcomes, float)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & (p < hi if i < bins - 1 else p <= hi)
        if m.sum() == 0:
            continue
        out.append({
            "bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()),
            "mean_pred": round(float(p[m].mean()), 3),
            "observed": round(float(y[m].mean()), 3),
        })
    return out


def calibration_report(matches: list[dict]) -> dict:
    """Binary calibration of the sharp closing YES prob vs realised YES."""
    probs, ys = [], []
    for m in matches:
        if m.get("resolved_yes") is None:
            continue
        tl = [r for r in m.get("timeline", []) if r.get("fair_yes") is not None]
        if not tl:
            continue
        probs.append(tl[-1]["fair_yes"])               # closing fair prob
        ys.append(1.0 if m["resolved_yes"] else 0.0)
    if not probs:
        return {"n": 0}
    return {
        "n": len(probs),
        "brier": round(brier_binary(probs, ys), 4),
        "base_rate": round(float(np.mean(ys)), 4),
        "reliability": reliability_table(probs, ys),
    }


def bootstrap_mean_ci(values, clusters, iters: int = 5000, seed: int = 7,
                      alpha: float = 0.05) -> dict:
    """Cluster bootstrap: resample clusters (e.g. match-weeks) with replacement."""
    vals = np.asarray(values, float)
    cl = np.asarray(clusters)
    if len(vals) == 0:
        return {"mean": None}
    uniq = np.unique(cl)
    idx_by_cluster = {c: np.where(cl == c)[0] for c in uniq}
    rng = np.random.default_rng(seed)
    means = np.empty(iters)
    for i in range(iters):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        sample = np.concatenate([idx_by_cluster[c] for c in pick])
        means[i] = vals[sample].mean()
    return {
        "mean": round(float(vals.mean()), 4),
        "ci_low": round(float(np.quantile(means, alpha / 2)), 4),
        "ci_high": round(float(np.quantile(means, 1 - alpha / 2)), 4),
        "p_gt_0": round(float(np.mean(means > 0)), 4),
        "n": int(len(vals)), "n_clusters": int(len(uniq)),
    }


def lead_lag(matches: list[dict], max_lag_steps: int = 6) -> dict:
    """Cross-correlation of d(fair) at t vs d(pm) at t+k, pooled over matches.

    Positive best-lag => Polymarket reacts AFTER the sharp move (tradeable window).
    """
    pooled = {k: ([], []) for k in range(max_lag_steps + 1)}
    for m in matches:
        rows = [r for r in m.get("timeline", [])
                if r.get("fair_yes") is not None and r.get("pm_price") is not None]
        if len(rows) < max_lag_steps + 2:
            continue
        fair = np.array([r["fair_yes"] for r in rows])
        pm = np.array([r["pm_price"] for r in rows])
        dfair, dpm = np.diff(fair), np.diff(pm)
        for k in range(max_lag_steps + 1):
            if k < len(dfair):
                a, b = dfair[:len(dfair) - k], dpm[k:]
                n = min(len(a), len(b))
                pooled[k][0].extend(a[:n])
                pooled[k][1].extend(b[:n])
    corrs = {}
    for k, (a, b) in pooled.items():
        if len(a) > 5 and np.std(a) > 0 and np.std(b) > 0:
            corrs[k] = round(float(np.corrcoef(a, b)[0, 1]), 3)
    if not corrs:
        return {"note": "insufficient data for lead-lag"}
    best = max(corrs, key=lambda k: corrs[k])
    return {"corr_by_lag_steps": corrs, "best_lag_steps": best,
            "interpretation": "PM follows sharp moves" if best > 0 else "no exploitable lag"}
