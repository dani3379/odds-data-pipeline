"""Order book snapshot + taker (walk-the-book) fills.

Prices are probabilities in (0,1); sizes are share counts. A taker BUY consumes
asks from the best (lowest) up; a taker SELL consumes bids from the best
(highest) down -- giving a realistic VWAP fill and partial fills when the book
is too thin. This is what makes 'would it have filled?' honest.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OrderBook:
    token: str
    ts: float                                   # unix seconds of this snapshot
    bids: list[list[float]] = field(default_factory=list)   # [[price, size], ...] desc
    asks: list[list[float]] = field(default_factory=list)   # [[price, size], ...] asc

    @classmethod
    def from_clob(cls, token: str, ts: float, payload: dict) -> "OrderBook":
        def lv(side):
            return [[float(x["price"]), float(x["size"])] for x in payload.get(side, [])]
        b = sorted(lv("bids"), key=lambda x: -x[0])
        a = sorted(lv("asks"), key=lambda x: x[0])
        return cls(token=token, ts=ts, bids=b, asks=a)

    # --- top of book ---
    def best_bid(self):
        return self.bids[0][0] if self.bids else None

    def best_ask(self):
        return self.asks[0][0] if self.asks else None

    def mid(self):
        bb, ba = self.best_bid(), self.best_ask()
        return (bb + ba) / 2 if (bb is not None and ba is not None) else (bb or ba)

    def spread(self):
        bb, ba = self.best_bid(), self.best_ask()
        return (ba - bb) if (bb is not None and ba is not None) else None

    def size_at(self, side: str, price: float) -> float:
        """Resting size at a price level on `side` ('bid'/'ask') -> your queue ahead."""
        levels = self.bids if side == "bid" else self.asks
        return sum(s for p, s in levels if abs(p - price) < 1e-9)

    # --- taker fill ---
    def walk(self, side: str, size: float):
        """Marketable fill for `size`. side='buy' eats asks, 'sell' eats bids.

        Returns (filled_size, vwap_price, worst_price). Partial if book too thin.
        """
        levels = self.asks if side == "buy" else self.bids
        need, cost, worst = size, 0.0, None
        for price, avail in levels:
            take = min(need, avail)
            if take <= 0:
                continue
            cost += take * price
            worst = price
            need -= take
            if need <= 1e-9:
                break
        filled = size - need
        vwap = (cost / filled) if filled > 0 else None
        return filled, vwap, worst
