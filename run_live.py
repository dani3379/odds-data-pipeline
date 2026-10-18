#!/usr/bin/env python3
"""Live Polymarket paper-trader + order-book recorder.

Records the live order book + trades to data/live/ (building the dataset that
doesn't exist), and races several strategies (maker & taker) against it with
realistic fills -- no real money.

    python run_live.py                 # run continuously (Ctrl-C to stop)
    python run_live.py --seconds 120   # short smoke test
    python run_live.py --poll 10 --within-hours 24 --size 100

Fees: set --taker-fee / --maker-rebate to Polymarket's CURRENT sports schedule
(they added taker fees + maker rebates in 2026). Defaults are conservative-ish.
"""
from __future__ import annotations

import argparse

from poly_arb.live.broker import PaperBroker
from poly_arb.live.engine import Engine
from poly_arb.live.recorder import Recorder
from poly_arb.live.strategies import FadeDrift


def build_strategies(size):
    # race maker vs taker; exit on PRICE (take-profit/stop-loss), not the clock
    return [
        FadeDrift("taker_tp03_sl04", "taker", window_min=120, thr=0.05,
                  take_profit=0.03, stop_loss=0.04, size=size),
        FadeDrift("taker_tp05_sl05", "taker", window_min=240, thr=0.08,
                  take_profit=0.05, stop_loss=0.05, size=size),
        FadeDrift("maker_tp03_sl04", "maker", window_min=120, thr=0.05,
                  take_profit=0.03, stop_loss=0.04, size=size),
        FadeDrift("maker_tp05_sl05", "maker", window_min=240, thr=0.08,
                  take_profit=0.05, stop_loss=0.05, size=size),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, help="run for N seconds then stop (smoke test)")
    ap.add_argument("--ticks", type=int, help="run for N polling cycles then stop")
    ap.add_argument("--poll", type=float, default=300, help="seconds between polls (default 5 min)")
    ap.add_argument("--within-hours", type=float, default=48, help="track matches kicking off within N h")
    ap.add_argument("--size", type=float, default=100.0, help="shares per trade")
    ap.add_argument("--taker-fee", type=float, default=0.0, help="taker fee fraction of notional")
    ap.add_argument("--maker-rebate", type=float, default=0.0, help="maker rebate fraction of notional")
    args = ap.parse_args()

    broker = PaperBroker(taker_fee=args.taker_fee, maker_rebate=args.maker_rebate)
    engine = Engine(build_strategies(args.size), broker, Recorder(),
                    poll_interval=args.poll, within_hours=args.within_hours)
    engine.run(run_seconds=args.seconds, max_ticks=args.ticks)


if __name__ == "__main__":
    main()
