"""PaperBroker: realistic maker/taker fill simulation, fees, positions, P&L.

Maker realism (the part you asked for - "would my order have filled?"):
  - a resting limit order joins the book BEHIND the size already at its price
    (queue_ahead, taken from the live snapshot),
  - it fills only as real trades print THROUGH its price (consuming the queue
    first), or if the book later crosses it,
  - so you only get filled when the market actually comes to you -- often when
    it's moving against you (true adverse selection). No free fills.

Taker fills walk the live book for a VWAP price (partial if too thin).
Makers earn a rebate; takers pay a fee (both configurable per current schedule).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count

from .book import OrderBook

_ids = count(1)


@dataclass
class Order:
    strategy: str
    token: str
    side: str                 # 'buy' | 'sell'
    kind: str                 # 'maker' | 'taker'
    size: float
    price: float | None = None    # limit price for maker; ignored for taker
    ts: float = 0.0
    oid: int = field(default_factory=lambda: next(_ids))
    filled: float = 0.0
    avg_price: float = 0.0
    queue_ahead: float = 0.0
    status: str = "new"           # new | open | filled | partial | cancelled
    fee: float = 0.0
    rebate: float = 0.0

    @property
    def remaining(self):
        return self.size - self.filled


@dataclass
class Position:
    net: float = 0.0              # +long / -short (shares)
    avg_cost: float = 0.0
    realized: float = 0.0
    fees: float = 0.0
    rebates: float = 0.0

    def unrealized(self, mark):
        return (mark - self.avg_cost) * self.net if mark is not None else 0.0

    def pnl(self, mark):
        return self.realized - self.fees + self.rebates + self.unrealized(mark)


class PaperBroker:
    def __init__(self, taker_fee=0.0, maker_rebate=0.0, maker_fee=0.0):
        self.taker_fee = taker_fee
        self.maker_rebate = maker_rebate
        self.maker_fee = maker_fee
        self.books: dict[str, OrderBook] = {}
        self.resting: list[Order] = []
        self.positions: dict[tuple, Position] = {}
        self.fills: list[dict] = []

    # ---- position math (avg-cost) ----
    def _pos(self, strat, token):
        return self.positions.setdefault((strat, token), Position())

    def _apply(self, strat, token, side, size, price, fee=0.0, rebate=0.0,
               kind="", ts=0.0):
        p = self._pos(strat, token)
        p.fees += fee
        p.rebates += rebate
        qty = size if side == "buy" else -size
        if p.net == 0 or (p.net > 0) == (qty > 0):           # opening / adding
            tot = abs(p.net) + abs(qty)
            p.avg_cost = (p.avg_cost * abs(p.net) + price * abs(qty)) / tot
            p.net += qty
        else:                                                # reducing / flipping
            closing = min(abs(qty), abs(p.net))
            direction = 1 if p.net > 0 else -1
            p.realized += (price - p.avg_cost) * closing * direction
            p.net += qty
            if abs(qty) > closing:                           # flipped
                p.avg_cost = price
            elif abs(p.net) < 1e-12:
                p.net = 0.0
                p.avg_cost = 0.0
        self.fills.append({"strat": strat, "token": token, "side": side, "kind": kind,
                           "size": size, "price": price, "fee": fee, "rebate": rebate,
                           "ts": ts})

    # ---- market data in ----
    def on_book(self, book: OrderBook):
        self.books[book.token] = book
        for o in list(self.resting):                         # book may cross a resting maker
            self._try_cross(o, book)

    def on_trade(self, token, price, size, taker_side, ts=0.0):
        """taker_side: 'buy' = a buyer hit asks; 'sell' = a seller hit bids."""
        for o in list(self.resting):
            if o.token != token or o.status not in ("open", "partial"):
                continue
            hit = (o.side == "buy" and taker_side == "sell" and price <= o.price + 1e-9) or \
                  (o.side == "sell" and taker_side == "buy" and price >= o.price - 1e-9)
            if not hit:
                continue
            vol = size
            eat = min(o.queue_ahead, vol)                    # queue ahead fills first
            o.queue_ahead -= eat
            vol -= eat
            if vol > 1e-9 and o.remaining > 1e-9:
                self._fill(o, min(o.remaining, vol), o.price, maker=True)

    # ---- order entry ----
    def submit(self, o: Order):
        book = self.books.get(o.token)
        o.ts = o.ts or (book.ts if book else 0.0)
        if o.kind == "taker":
            self._taker(o, book)
        else:
            self._maker(o, book)
        return o

    def _taker(self, o, book, limit=None):
        if not book:
            o.status = "cancelled"
            return
        filled, vwap, _ = book.walk(o.side, o.remaining)
        if filled > 1e-9:
            self._fill(o, filled, vwap, maker=False)
        o.status = "filled" if o.remaining <= 1e-9 else ("partial" if o.filled else "cancelled")

    def _maker(self, o, book):
        if book:
            ba, bb = book.best_ask(), book.best_bid()
            marketable = (o.side == "buy" and ba is not None and o.price >= ba) or \
                         (o.side == "sell" and bb is not None and o.price <= bb)
            if marketable:                                   # crosses -> fills as taker now
                self._taker(o, book)
                return
            o.queue_ahead = book.size_at("bid" if o.side == "buy" else "ask", o.price)
        o.status = "open"
        self.resting.append(o)

    def _try_cross(self, o, book):
        if o.status not in ("open", "partial"):
            return
        ba, bb = book.best_ask(), book.best_bid()
        cross = (o.side == "buy" and ba is not None and ba <= o.price) or \
                (o.side == "sell" and bb is not None and bb >= o.price)
        if cross:
            # the book moved through your resting price -> you get filled at your limit
            avail = book.size_at("ask" if o.side == "buy" else "bid",
                                 ba if o.side == "buy" else bb)
            self._fill(o, min(o.remaining, max(avail, 0.0)), o.price, maker=True)

    def _fill(self, o, size, price, maker):
        notional = size * price
        fee = (self.maker_fee if maker else self.taker_fee) * notional
        rebate = self.maker_rebate * notional if maker else 0.0
        o.filled += size
        o.avg_price = price
        o.fee += fee
        o.rebate += rebate
        o.status = "filled" if o.remaining <= 1e-9 else "partial"
        if o in self.resting and o.status == "filled":
            self.resting.remove(o)
        self._apply(o.strategy, o.token, o.side, size, price, fee, rebate,
                    kind=("maker" if maker else "taker"), ts=o.ts)

    # ---- helpers ----
    def cancel(self, o):
        if o in self.resting:
            self.resting.remove(o)
        o.status = "cancelled"

    def flatten(self, strat, token, ts=0.0):
        """Taker-close the net position (e.g. before kickoff)."""
        p = self.positions.get((strat, token))
        if not p or abs(p.net) < 1e-9:
            return None
        side = "sell" if p.net > 0 else "buy"
        return self.submit(Order(strat, token, side, "taker", abs(p.net), ts=ts))

    def flatten_all(self, token, ts=0.0):
        for (strat, tk) in [k for k in self.positions if k[1] == token]:
            self.flatten(strat, token, ts)

    def mark_price(self, token):
        b = self.books.get(token)
        return b.mid() if b else None

    def equity(self, strat=None):
        total = 0.0
        for (s, tk), p in self.positions.items():
            if strat and s != strat:
                continue
            total += p.pnl(self.mark_price(tk))
        return total
