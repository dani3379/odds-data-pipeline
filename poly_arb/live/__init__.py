"""Live paper-trading + market recorder for Polymarket.

Two jobs at once:
  1. RECORD the live order book + trades to disk (the order-book history that
     doesn't exist anywhere else -> builds your real dataset going forward).
  2. PAPER-TRADE many strategies against that live data with realistic fills
     (maker AND taker), so you can see what WOULD have filled and what it earns
     -- a full simulation, no real money.

Modules:
  book.py        OrderBook + taker walk-the-book
  broker.py      PaperBroker: maker queue fills, taker fills, fees, positions, PnL
  strategies.py  strategy interface + the fade-drift pattern we found
  feed.py        Polymarket live data (discover matches, fetch book + trades)
  recorder.py    append-only JSONL persistence
  engine.py      the loop that ties it together
"""
