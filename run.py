#!/usr/bin/env python3
"""poly_arb CLI.

    python run.py demo                 # full engine on synthetic data (no network/keys)
    python run.py discover             # find Polymarket WC/PL markets (free)
    python run.py fetch                # pull PM price history + (PAID) historical odds
    python run.py build                # link + align into per-match timelines
    python run.py backtest             # simulate trades, P&L, CLV
    python run.py report               # calibration + bootstrap + lead-lag
    python run.py pipeline             # discover -> fetch -> build -> report

Run `demo` first to see the pipeline work end-to-end before touching real data.
Set your key in the env to enable PAID odds fetching:
    $env:ODDS_API_KEY = "your_key"
"""
from __future__ import annotations

import argparse
import json
import re

from poly_arb import config, dataset, oddsapi, polymarket, stats, synth
from poly_arb.backtest import run_backtest, summarize, trades_to_dicts
from poly_arb.util import load_json, log, parse_iso, save_json

PM_MARKETS = config.PROC / "pm_markets.json"
BUNDLES = config.PROC / "bundles"
MATCHES_FILE = config.PROC / "matches.json"
TRADES_FILE = config.OUT / "trades.json"
REPORT_FILE = config.OUT / "report.json"
BUNDLES.mkdir(parents=True, exist_ok=True)


def _pretty(title, obj):
    print(f"\n=== {title} ===")
    print(json.dumps(obj, indent=2, default=str))


# --------------------------------------------------------------------------- #
def cmd_demo(s):
    log("generating synthetic dataset (200 matches)...")
    matches = synth.make_dataset(n=200, seed=s.rng_seed, s=s)
    save_json(MATCHES_FILE, matches)
    _run_and_report(matches, s)
    print("\nSynthetic demonstration complete. Lag and mispricing are built into these inputs.")
    print("These results illustrate the pipeline; they do not establish live-market performance.")


def cmd_discover(s):
    status = "all" if s.include_finished else "active"
    log(f"searching Polymarket for per-match markets by team (status={status})...")
    markets = polymarket.search_match_markets(events_status=status)
    win_re = re.compile(r"\bwin\b|draw", re.I)       # win/draw only (skip O/U, spreads)
    markets = [m for m in markets if win_re.search(m.question)]
    if s.include_finished:                            # backtesting needs RESOLVED games
        markets = [m for m in markets if m.closed and m.resolved_yes is not None]
    polymarket.save_markets(markets, PM_MARKETS)
    kind = "FINISHED/resolved" if s.include_finished else "upcoming"
    log(f"saved {len(markets)} {kind} match win/draw markets -> {PM_MARKETS}")
    for m in markets[:12]:
        out = {True: "YES", False: "no", None: "?"}[m.resolved_yes]
        log(f"    [{str(m.kickoff_utc)[:16]}] {m.question[:50]:50} YES={m.yes_label[:14]:14} -> {out}")


def cmd_fetch(s):
    if not PM_MARKETS.exists():
        log("no pm_markets.json - run `discover` first."); return
    markets = load_json(PM_MARKETS)
    has_key = bool(s.odds_api_key)
    if not has_key:
        log("NO ODDS_API_KEY set -> fetching FREE Polymarket data only (no odds).")
    else:
        log(f"ODDS_API_KEY present -> historical odds WILL be billed "
            f"(lookback={s.lookback_hours}h, every {s.snap_minutes}min). Cache prevents re-bills.")

    n_ok = 0
    for mk in markets:
        cond = mk.get("condition_id")
        if not cond:
            continue
        log(f"fetch {mk.get('question','?')[:55]}")
        price_history = polymarket.fetch_price_history(mk["token_yes"])
        trades = polymarket.fetch_trades(cond)

        odds_snapshots = []
        kickoff = mk.get("kickoff_utc")
        if has_key and kickoff:
            subject = dataset.extract_subject(mk.get("question", ""))
            sports = dataset.sport_for_title(
                f"{mk.get('event_title','')} {mk.get('question','')}", s.sport_keys)
            for sport in sports:
                try:
                    snaps = oddsapi.iter_snapshots(sport, parse_iso(kickoff), s.odds_api_key, s)
                except Exception as e:                               # noqa: BLE001
                    log(f"  odds fetch failed for {sport}: {e}"); continue
                for snap in snaps:
                    games = snap["games"]
                    if subject:
                        games = [g for g in games if dataset.game_matches_subject(subject, g)]
                    if games:
                        odds_snapshots.append({"t": snap["t"], "games": games})
                if odds_snapshots:
                    break                                            # right sport found

        bundle = {
            "market": mk,
            "sport_keys": dataset.sport_for_title(
                f"{mk.get('event_title','')} {mk.get('question','')}", s.sport_keys),
            "price_history": price_history,
            "trades_count": len(trades),
            "odds_snapshots": odds_snapshots,
        }
        save_json(BUNDLES / f"{cond}.json", bundle)
        n_ok += 1
    log(f"wrote {n_ok} bundles -> {BUNDLES}")


def cmd_build(s):
    files = sorted(BUNDLES.glob("*.json"))
    if not files:
        log("no bundles - run `fetch` first."); return
    matches, linked = [], 0
    for f in files:
        m = dataset.build_match_from_bundle(load_json(f), s)
        if m:
            matches.append(m); linked += 1
    save_json(MATCHES_FILE, matches)
    log(f"built {linked}/{len(files)} matches (rest unlinkable / no data) -> {MATCHES_FILE}")
    if linked < len(files):
        log("Unlinked markets usually = team-name mismatch; extend ALIASES in dataset.py.")


def cmd_backtest(s):
    if not MATCHES_FILE.exists():
        log("no matches.json - run `demo` or `build` first."); return
    trades = run_backtest(load_json(MATCHES_FILE), s)
    save_json(TRADES_FILE, trades_to_dicts(trades))
    _pretty("BACKTEST SUMMARY", summarize(trades))
    log(f"trades -> {TRADES_FILE}")


def cmd_report(s):
    if not MATCHES_FILE.exists():
        log("no matches.json - run `demo` or `build` first."); return
    _run_and_report(load_json(MATCHES_FILE), s)


def cmd_cadence(s):
    """Measure the REAL odds-side snapshot spacing (a few paid credits)."""
    if not s.odds_api_key:
        log("set ODDS_API_KEY first: $env:ODDS_API_KEY = 'your_key'"); return
    sport = next((k for k in s.sport_keys if "world_cup" in k or "fifa" in k), s.sport_keys[0])
    # default to ~2 days ago, when in-season matches existed; override via --date
    from datetime import timedelta
    from poly_arb.util import utcnow, iso as _iso
    when = _iso(utcnow() - timedelta(days=2))
    log(f"probing native cadence: {sport} around {when} (~6 calls)...")
    res = oddsapi.probe_cadence(sport, s.odds_api_key, s.regions, when, steps=6)
    _pretty("ODDS PROGRESSION CADENCE", res)
    if res.get("meets_30min"):
        log("native cadence <= 30 min -> the progression is genuinely fine-grained. GO.")
    else:
        log("native cadence COARSER than 30 min -> progression is limited; reconsider before paying.")


def cmd_pipeline(s):
    cmd_discover(s)
    cmd_fetch(s)
    cmd_build(s)
    cmd_report(s)


def _run_and_report(matches, s):
    trades = run_backtest(matches, s)
    save_json(TRADES_FILE, trades_to_dicts(trades))
    summ = summarize(trades)
    _pretty("BACKTEST SUMMARY", summ)

    settled = [t for t in trades if t.won is not None]
    clusters = [next((m["match_week"] for m in matches if m["match_id"] == t.match_id),
                     t.match_id) for t in settled]
    report = {
        "backtest": summ,
        "calibration": stats.calibration_report(matches),
        "lead_lag": stats.lead_lag(matches),
        "returns_bootstrap": stats.bootstrap_mean_ci(
            [t.ret for t in settled], clusters, s.bootstrap_iters, s.rng_seed),
        "clv_bootstrap": stats.bootstrap_mean_ci(
            [t.clv_price for t in settled], clusters, s.bootstrap_iters, s.rng_seed),
    }
    save_json(REPORT_FILE, report)
    _pretty("CALIBRATION (sharp benchmark)", report["calibration"])
    _pretty("LEAD-LAG (does PM follow sharp?)", report["lead_lag"])
    _pretty("RETURNS 95% CI (clustered bootstrap)", report["returns_bootstrap"])
    _pretty("CLV 95% CI", report["clv_bootstrap"])
    log(f"report -> {REPORT_FILE}")


COMMANDS = {
    "demo": cmd_demo, "discover": cmd_discover, "fetch": cmd_fetch,
    "build": cmd_build, "backtest": cmd_backtest, "report": cmd_report,
    "pipeline": cmd_pipeline, "cadence": cmd_cadence,
}


def main():
    ap = argparse.ArgumentParser(description="poly_arb backtesting CLI")
    ap.add_argument("command", choices=list(COMMANDS))
    ap.add_argument("--edge", type=float, help="override edge threshold")
    ap.add_argument("--half-spread", type=float, help="override assumed half-spread cost")
    args = ap.parse_args()

    s = config.load()
    if args.edge is not None:
        s.edge_threshold = args.edge
    if args.half_spread is not None:
        s.half_spread = args.half_spread
    COMMANDS[args.command](s)


if __name__ == "__main__":
    main()
