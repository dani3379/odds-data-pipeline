"""Backtest engine: turn aligned timelines into trades, P&L and CLV.

This is a TIER-1 backtest: Polymarket fills are modelled from the historical
mid/last price plus an assumed half-spread + fee + slippage, because historical
order-book DEPTH is not retrievable. Treat results as optimistic on fills until
validated with live order-book capture. All costs are explicit and tunable.

No look-ahead: each decision at row time t uses only fields known at t; CLV is
computed against the closing row but is never used to decide entry.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from .config import Settings


@dataclass
class Trade:
    match_id: str
    league: str
    entry_t: str
    mins_to_ko: float
    fair_yes: float
    entry_price: float        # effective cost incl. spread+fee+slippage
    edge: float
    stake: float
    shares: float
    won: Optional[bool]
    pnl: float
    ret: float                # pnl / stake
    clv_price: float          # closing PM price - entry_price
    clv_fair: float           # closing sharp fair - entry_price


def _effective_cost(pm_price: float, s: Settings) -> float:
    return pm_price + s.half_spread + s.fee + s.slippage


def _kelly_fraction(p: float, cost: float, s: Settings) -> float:
    if cost <= 0 or cost >= 1:
        return 0.0
    edge = p - cost
    if edge <= 0:
        return 0.0
    full = edge / (1.0 - cost)          # Kelly for a 0/1 contract priced at cost
    return min(s.kelly_fraction * full, s.kelly_cap)


def simulate_match(match: dict, s: Settings) -> list[Trade]:
    rows = [r for r in match.get("timeline", []) if r.get("pm_price") is not None]
    if not rows:
        return []
    closing = rows[-1]                                   # row nearest kickoff
    close_pm = closing.get("pm_price")
    close_fair = closing.get("fair_yes")
    resolved = match.get("resolved_yes")

    trades: list[Trade] = []
    for r in rows:
        fair, pm = r.get("fair_yes"), r.get("pm_price")
        if fair is None or pm is None:
            continue
        cost = _effective_cost(pm, s)
        edge = fair - cost
        if edge < s.edge_threshold:
            continue
        f = _kelly_fraction(fair, cost, s)
        if f <= 0:
            continue
        stake = f * s.bankroll
        shares = stake / cost
        won = bool(resolved) if resolved is not None else None
        payoff = shares if won else 0.0
        pnl = payoff - stake if won is not None else 0.0
        trades.append(Trade(
            match_id=match["match_id"], league=match.get("league", ""),
            entry_t=r["t"], mins_to_ko=r.get("mins_to_ko", 0.0),
            fair_yes=round(fair, 4), entry_price=round(cost, 4), edge=round(edge, 4),
            stake=round(stake, 2), shares=round(shares, 2), won=won,
            pnl=round(pnl, 2), ret=round(pnl / stake, 4) if stake else 0.0,
            clv_price=round((close_pm - cost), 4) if close_pm is not None else 0.0,
            clv_fair=round((close_fair - cost), 4) if close_fair is not None else 0.0,
        ))
        if s.one_bet_per_market:
            break
    return trades


def run_backtest(matches: list[dict], s: Settings) -> list[Trade]:
    out: list[Trade] = []
    for m in matches:
        out.extend(simulate_match(m, s))
    return out


def summarize(trades: list[Trade]) -> dict:
    if not trades:
        return {"n_trades": 0}
    settled = [t for t in trades if t.won is not None]
    stake = sum(t.stake for t in settled)
    pnl = sum(t.pnl for t in settled)
    wins = sum(1 for t in settled if t.won)
    rets = [t.ret for t in settled]
    return {
        "n_trades": len(trades),
        "n_settled": len(settled),
        "hit_rate": round(wins / len(settled), 4) if settled else None,
        "total_stake": round(stake, 2),
        "total_pnl": round(pnl, 2),
        "roi": round(pnl / stake, 4) if stake else None,
        "mean_ret": round(sum(rets) / len(rets), 4) if rets else None,
        "mean_edge": round(sum(t.edge for t in trades) / len(trades), 4),
        "mean_clv_price": round(sum(t.clv_price for t in trades) / len(trades), 4),
        "mean_clv_fair": round(sum(t.clv_fair for t in trades) / len(trades), 4),
    }


def trades_to_dicts(trades: list[Trade]) -> list[dict]:
    return [asdict(t) for t in trades]
