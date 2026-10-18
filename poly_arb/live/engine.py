"""The live loop: poll -> record -> update books/trades -> run strategies ->
simulate fills -> track P&L. Runs continuously (or for a fixed smoke-test span).
"""
from __future__ import annotations

import time
import traceback

from .. import polymarket
from ..util import log, parse_iso, utcnow
from . import feed
from .db import DB
from .recorder import Recorder

MAX_SERIES = 3000


class Engine:
    def __init__(self, strategies, broker, recorder=None, db=None,
                 poll_interval=15, refresh_interval=1800, within_hours=48):
        self.strategies = strategies
        self.broker = broker
        self.recorder = recorder or Recorder()
        self.db = db or DB()
        self.poll_interval = poll_interval
        self.refresh_interval = refresh_interval
        self.within_hours = within_hours
        self.markets: dict[str, dict] = {}        # token -> market
        self.series: dict[str, list] = {}
        self.last_trade_ts: dict[str, float] = {}
        self._last_refresh = 0.0
        self._persisted_fills = 0

    # ---- market discovery ----
    def refresh(self):
        try:
            found = feed.discover_matches(self.within_hours)
        except Exception as e:                                  # noqa: BLE001
            log(f"discover failed: {e}"); return
        now = utcnow().timestamp()
        for m in found:
            tok = m["token"]
            if tok not in self.markets:
                self.markets[tok] = m
                self._seed_series(tok, m)
                self.db.upsert_market(m, now)
                log(f"tracking: {m['question'][:55]} (KO in {(m['kickoff']-now)/3600:.1f}h)")
        self.db.commit()
        for tok in [t for t, m in self.markets.items() if utcnow().timestamp() > m["kickoff"]]:
            self.broker.flatten_all(tok)
            self.markets.pop(tok, None)
        self._last_refresh = now

    def _seed_series(self, token, m):
        """Backfill the mid series from free price-history so strategies act now."""
        try:
            hist = polymarket.fetch_price_history(token)
            self.series[token] = [(float(p["t"]), float(p["p"])) for p in hist
                                  if p.get("t") and p.get("p") is not None][-MAX_SERIES:]
        except Exception:                                       # noqa: BLE001
            self.series[token] = []

    # ---- one polling cycle ----
    def tick(self):
        now = utcnow().timestamp()
        for tok, m in list(self.markets.items()):
            try:
                book = feed.fetch_book(tok, now)
                self.recorder.book(book)
                self.broker.on_book(book)

                trades, mx = feed.fetch_trades(m["condition"], tok, self.last_trade_ts.get(tok, 0.0))
                self.last_trade_ts[tok] = mx
                self.recorder.trades(tok, trades)
                for t in trades:
                    self.broker.on_trade(tok, t["price"], t["size"], t["taker_side"], t["ts"])

                mid = book.mid()
                if mid is not None:
                    s = self.series.setdefault(tok, [])
                    s.append((now, mid))
                    del s[:-MAX_SERIES]

                for strat in self.strategies:
                    strat.step(tok, book, self.series[tok], self.broker, now, m["kickoff"])
            except Exception as e:                              # noqa: BLE001
                log(f"tick error {tok[:10]}: {e}")

    # ---- run ----
    def run(self, run_seconds=None, max_ticks=None):
        log(f"engine start: {len(self.strategies)} strategies, "
            f"poll={self.poll_interval}s, within={self.within_hours}h")
        self.refresh()
        start, ticks = time.time(), 0
        try:
            while True:
                if utcnow().timestamp() - self._last_refresh > self.refresh_interval:
                    self.refresh()
                self.tick()
                self._persist()
                ticks += 1
                self.report()
                if max_ticks and ticks >= max_ticks:
                    break
                if run_seconds and time.time() - start >= run_seconds:
                    break
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            log("stopped by user")
        self.recorder.close()
        self.db.close()
        self.report(final=True)

    def _persist(self):
        now = utcnow().timestamp()
        for f in self.broker.fills[self._persisted_fills:]:
            self.db.insert_fill(f.get("ts") or now, f)
        self._persisted_fills = len(self.broker.fills)
        for s in self.strategies:
            nf = sum(1 for f in self.broker.fills if f["strat"] == s.name)
            self.db.insert_equity(now, s.name, self.broker.equity(s.name), nf)
        self.db.commit()

    def report(self, final=False):
        line = " | ".join(
            f"{s.name}: {self.broker.equity(s.name):+.2f} "
            f"({sum(1 for f in self.broker.fills if f['strat'] == s.name)} fills)"
            for s in self.strategies)
        log(("FINAL  " if final else "P&L    ") + line)
