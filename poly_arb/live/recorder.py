"""Parquet recorder for the live order book + trades.

Buffers rows and flushes to date-partitioned Parquet (columnar, compressed).
At a multi-minute poll cadence we buffer ALL tokens together per flush so we
write a handful of files per day instead of thousands of tiny ones. The token
is a column, so different markets never collide.

Robustness: flushes every `flush_every` rows or `flush_seconds`, and on close().
Worst-case data loss on a hard crash is one flush window.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .. import config

LEVELS = 10


class Recorder:
    def __init__(self, root: Path | None = None, flush_every=120, flush_seconds=600):
        self.root = root or (config.DATA / "live")
        (self.root / "books").mkdir(parents=True, exist_ok=True)
        (self.root / "trades").mkdir(parents=True, exist_ok=True)
        self.flush_every = flush_every
        self.flush_seconds = flush_seconds
        self._buf: dict[str, list] = {"books": [], "trades": []}
        self._last: dict[str, float] = {"books": 0.0, "trades": 0.0}

    def book(self, b):
        row = {"ts": b.ts, "token": b.token, "mid": b.mid(), "spread": b.spread()}
        for i in range(LEVELS):
            row[f"bid_px_{i}"] = b.bids[i][0] if i < len(b.bids) else None
            row[f"bid_sz_{i}"] = b.bids[i][1] if i < len(b.bids) else None
            row[f"ask_px_{i}"] = b.asks[i][0] if i < len(b.asks) else None
            row[f"ask_sz_{i}"] = b.asks[i][1] if i < len(b.asks) else None
        self._add("books", row)

    def trades(self, token, trades):
        for t in trades:
            self._add("trades", {**t, "token": token})

    def _add(self, kind, row):
        buf = self._buf[kind]
        buf.append(row)
        if len(buf) >= self.flush_every or \
           (buf and time.time() - self._last[kind] > self.flush_seconds):
            self._flush(kind)

    def _flush(self, kind):
        buf = self._buf[kind]
        if not buf:
            return
        day = datetime.fromtimestamp(buf[0]["ts"], timezone.utc).strftime("%Y%m%d")
        d = self.root / kind / f"date={day}"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{kind}_{int(time.time() * 1000)}.parquet"
        pd.DataFrame(buf).to_parquet(path, index=False)
        self._buf[kind] = []
        self._last[kind] = time.time()

    def close(self):
        for kind in ("books", "trades"):
            self._flush(kind)
