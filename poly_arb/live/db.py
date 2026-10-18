"""SQLite store for structured paper-trading state: fills, equity, markets.

Single file, SQL-queryable, transactional, stdlib-only (no extra deps). Lets you
ask "what did maker_tp03 fill today and at what P&L?" with a query, and lets the
engine persist/restart safely. The big time-series (book/trades) go to Parquet;
this holds the relational bits.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS fills(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, strategy TEXT, token TEXT, side TEXT, kind TEXT,
  size REAL, price REAL, fee REAL, rebate REAL);
CREATE TABLE IF NOT EXISTS equity(
  ts REAL, strategy TEXT, equity REAL, n_fills INTEGER);
CREATE TABLE IF NOT EXISTS markets(
  token TEXT PRIMARY KEY, condition TEXT, question TEXT,
  kickoff REAL, label TEXT, first_seen REAL);
CREATE INDEX IF NOT EXISTS ix_fills_strat ON fills(strategy);
CREATE INDEX IF NOT EXISTS ix_equity_strat ON equity(strategy);
"""


class DB:
    def __init__(self, path: Path | None = None):
        self.path = path or (config.DATA / "live" / "paper.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        self.con.commit()

    def insert_fill(self, ts, f):
        self.con.execute(
            "INSERT INTO fills(ts,strategy,token,side,kind,size,price,fee,rebate)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (ts or f.get("ts"), f["strat"], f["token"], f["side"], f.get("kind", ""),
             f["size"], f["price"], f.get("fee", 0.0), f.get("rebate", 0.0)))

    def insert_equity(self, ts, strategy, equity, n_fills):
        self.con.execute("INSERT INTO equity(ts,strategy,equity,n_fills) VALUES(?,?,?,?)",
                         (ts, strategy, equity, n_fills))

    def upsert_market(self, m, first_seen):
        self.con.execute(
            "INSERT OR IGNORE INTO markets(token,condition,question,kickoff,label,first_seen)"
            " VALUES(?,?,?,?,?,?)",
            (m["token"], m["condition"], m["question"], m["kickoff"], m["label"], first_seen))

    def commit(self):
        self.con.commit()

    def close(self):
        self.con.commit()
        self.con.close()

    # --- read helpers ---
    def summary(self):
        cur = self.con.execute(
            "SELECT strategy, COUNT(*), ROUND(SUM(rebate-fee),4) FROM fills GROUP BY strategy")
        return cur.fetchall()
