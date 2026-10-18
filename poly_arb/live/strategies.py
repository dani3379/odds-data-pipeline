"""Strategies that run live against the paper broker.

Each runs independently (positions are keyed by strategy name), so you can race
many variants -- maker vs taker, different windows/thresholds -- side by side in
real conditions. FadeDrift implements the slow-drift mean-reversion we found.
"""
from __future__ import annotations

from .broker import Order


def _price_at(series, t):
    """Last mid with ts <= t (no look-ahead). series = [(ts, mid), ...]."""
    val = None
    for ts, m in series:
        if ts <= t:
            val = m
        else:
            break
    return val


class Strategy:
    name = "base"

    def step(self, token, book, series, broker, now, kickoff):
        raise NotImplementedError


class FadeDrift(Strategy):
    """Fade a slow multi-hour drift; exit on a PRICE move, not the clock.

    Triple-barrier exit (Lopez de Prado): close when the price has reverted by
    `take_profit` (the win), or moved `stop_loss` against us (the cut), or the
    `max_hold`/kickoff vertical barrier hits (fallback). This is the user's
    "wait for the price to come back instead of waiting hours".

    kind='taker' crosses the spread to enter; kind='maker' posts a passive limit.
    """

    def __init__(self, name, kind="taker", window_min=120, thr=0.05,
                 take_profit=0.03, stop_loss=0.04, max_hold_min=360,
                 band=(0.20, 0.80), size=100.0, exit_buffer_min=10):
        self.name = name
        self.kind = kind
        self.window_s = window_min * 60
        self.thr = thr
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.max_hold_s = max_hold_min * 60
        self.band = band
        self.size = size
        self.exit_buffer_s = exit_buffer_min * 60
        self.state: dict = {}

    def step(self, token, book, series, broker, now, kickoff):
        st = self.state.setdefault(token, {})
        pos = broker.positions.get((self.name, token))
        have = pos and abs(pos.net) > 1e-9

        # 1) manage exit: PRICE-triggered take-profit / stop-loss, time as fallback
        if have:
            st.setdefault("entry_ts", now)
            mark = book.mid()
            if mark is not None:
                fav = (mark - pos.avg_cost) * (1 if pos.net > 0 else -1)   # +ve = reverting our way
                hit_tp = fav >= self.take_profit
                hit_sl = fav <= -self.stop_loss
            else:
                hit_tp = hit_sl = False
            time_up = now >= st["entry_ts"] + self.max_hold_s
            near_ko = kickoff and now >= kickoff - self.exit_buffer_s
            if hit_tp or hit_sl or time_up or near_ko:
                broker.flatten(self.name, token, now)
                st.clear()
            return

        # 2) waiting on an unfilled maker order? cancel if stale
        o = st.get("order")
        if o is not None:
            if o.status in ("open", "partial") and (now - o.ts) > self.window_s:
                broker.cancel(o)
                st["order"] = None
            elif o.status in ("open", "partial"):
                return                       # still resting, give it time
            else:
                st["order"] = None           # filled handled as a position next tick

        # 3) entry signal: a drift over `window`, on a balanced price
        mid = book.mid()
        if mid is None or not (self.band[0] <= mid <= self.band[1]):
            return
        if kickoff and now >= kickoff - self.exit_buffer_s:
            return                           # too close to KO to open
        past = _price_at(series, now - self.window_s)
        if past is None:
            return
        drift = mid - past
        if abs(drift) < self.thr:
            return
        side = "sell" if drift > 0 else "buy"     # fade the move

        if self.kind == "taker":
            filled = broker.submit(Order(self.name, token, side, "taker", self.size, ts=now))
            if filled.filled > 1e-9:
                st["entry_ts"] = now
        else:
            px = book.best_ask() if side == "sell" else book.best_bid()
            if px is None:
                return
            o = broker.submit(Order(self.name, token, side, "maker", self.size, price=px, ts=now))
            st["order"] = o                              # entry_ts set when the fill lands
