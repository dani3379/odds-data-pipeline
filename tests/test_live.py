"""Tests for the live fill engine (the realism-critical part). No network.
Run: python tests/test_live.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poly_arb.live.book import OrderBook
from poly_arb.live.broker import PaperBroker, Order


def book(token="t", ts=0.0, bids=None, asks=None):
    b = OrderBook(token, ts)
    b.bids = bids or []
    b.asks = asks or []
    return b


def test_taker_walk_vwap():
    bk = book(asks=[[0.50, 100], [0.51, 200]])
    filled, vwap, worst = bk.walk("buy", 150)
    assert abs(filled - 150) < 1e-9
    assert abs(vwap - (100 * 0.50 + 50 * 0.51) / 150) < 1e-9
    assert worst == 0.51


def test_taker_partial_when_thin():
    bk = book(asks=[[0.50, 100]])
    filled, vwap, _ = bk.walk("buy", 500)
    assert abs(filled - 100) < 1e-9 and abs(vwap - 0.50) < 1e-9


def test_taker_fill_and_fee():
    br = PaperBroker(taker_fee=0.01)
    br.on_book(book(asks=[[0.50, 1000]]))
    o = br.submit(Order("s", "t", "buy", "taker", 100))
    assert o.status == "filled" and abs(o.avg_price - 0.50) < 1e-9
    assert abs(o.fee - 0.01 * 100 * 0.50) < 1e-9
    assert abs(br.positions[("s", "t")].net - 100) < 1e-9


def test_maker_queue_then_fill():
    br = PaperBroker(maker_rebate=0.002)
    # resting bid of 100 at 0.49 -> we join behind it (queue_ahead=100)
    br.on_book(book(bids=[[0.49, 100]], asks=[[0.51, 100]]))
    o = br.submit(Order("s", "t", "buy", "maker", 80, price=0.49))
    assert o.status == "open" and abs(o.queue_ahead - 100) < 1e-9
    # a seller hits 0.49 for 100 -> all eaten by the queue ahead, we get nothing
    br.on_trade("t", 0.49, 100, "sell")
    assert o.filled == 0
    # another seller hits 0.49 for 120 -> queue gone, we fill our 80
    br.on_trade("t", 0.49, 120, "sell")
    assert abs(o.filled - 80) < 1e-9 and o.status == "filled"
    assert o.rebate > 0                                   # earned a maker rebate


def test_maker_not_filled_when_price_not_reached():
    br = PaperBroker()
    br.on_book(book(bids=[[0.49, 0]], asks=[[0.55, 100]]))
    o = br.submit(Order("s", "t", "buy", "maker", 50, price=0.49))
    br.on_trade("t", 0.52, 100, "sell")                  # trades above our bid -> no fill
    assert o.filled == 0 and o.status == "open"


def test_book_cross_fills_resting_maker():
    br = PaperBroker()
    br.on_book(book(bids=[[0.40, 50]], asks=[[0.60, 100]]))
    o = br.submit(Order("s", "t", "buy", "maker", 30, price=0.50))
    # ask collapses through our 0.50 bid -> we get filled at our limit
    br.on_book(book(bids=[[0.40, 50]], asks=[[0.49, 80]]))
    assert o.filled > 0 and abs(o.avg_price - 0.50) < 1e-9


def test_realized_pnl_and_flatten():
    br = PaperBroker()
    br.on_book(book(asks=[[0.50, 1000]], bids=[[0.50, 1000]]))
    br.submit(Order("s", "t", "buy", "taker", 100))      # long 100 @0.50
    br.on_book(book(asks=[[0.60, 1000]], bids=[[0.60, 1000]]))
    br.flatten("s", "t")                                  # sell 100 @0.60
    p = br.positions[("s", "t")]
    assert abs(p.net) < 1e-9
    assert abs(p.realized - (0.60 - 0.50) * 100) < 1e-6


def test_fade_drift_full_trade_lifecycle():
    """Signal -> entry -> take-profit exit -> realized profit, end to end."""
    from poly_arb.live.strategies import FadeDrift
    br = PaperBroker()
    s = FadeDrift("ft", "taker", window_min=120, thr=0.05, take_profit=0.03,
                  stop_loss=0.20, max_hold_min=600, band=(0.1, 0.9), size=100)
    t0 = 1_000_000.0
    series = [(t0 + i * 600, 0.50 + 0.08 * (i / 12)) for i in range(13)]   # rising 0.50->0.58
    now = series[-1][0]
    bk = book("t", now, bids=[[0.58, 1000]], asks=[[0.59, 1000]])
    br.on_book(bk)
    s.step("t", bk, series, br, now, kickoff=now + 1e6)
    pos = br.positions.get(("ft", "t"))
    assert pos and pos.net < 0, "should have faded the up-drift by going short"

    # price reverts down -> take-profit should close it for a gain
    now2 = now + 600
    series.append((now2, 0.535))
    bk2 = book("t", now2, bids=[[0.53, 1000]], asks=[[0.54, 1000]])
    br.on_book(bk2)
    s.step("t", bk2, series, br, now2, kickoff=now2 + 1e6)
    pos = br.positions.get(("ft", "t"))
    assert abs(pos.net) < 1e-9, "take-profit should have flattened the position"
    assert pos.realized > 0, "reversion fade should be profitable here"


def test_db_roundtrip(tmp=None):
    import tempfile
    from poly_arb.live.db import DB
    d = DB(Path(tempfile.mkdtemp()) / "t.db")
    d.insert_fill(1.0, {"strat": "x", "token": "tk", "side": "buy", "kind": "taker",
                        "size": 100, "price": 0.5, "fee": 0.1, "rebate": 0.0})
    d.commit()
    assert d.summary()[0][1] == 1
    d.close()


def test_recorder_parquet(tmp=None):
    import tempfile
    import pandas as pd
    from poly_arb.live.recorder import Recorder
    root = Path(tempfile.mkdtemp())
    r = Recorder(root=root, flush_every=1)
    r.book(book("tok123", 1_700_000_000.0, bids=[[0.49, 50]], asks=[[0.51, 60]]))
    files = list(root.glob("books/date=*/*.parquet"))
    assert files, "expected a parquet file"
    df = pd.read_parquet(files[0])
    assert abs(df.iloc[0]["mid"] - 0.50) < 1e-9 and df.iloc[0]["token"] == "tok123"


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} live-engine tests passed.")


if __name__ == "__main__":
    _run()
