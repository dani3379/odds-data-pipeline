"""Configuration: paths, API keys (from env), and all tunable parameters.

Nothing secret is hard-coded. Set your key in the environment:
    PowerShell:  $env:ODDS_API_KEY = "your_free_key"
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("ODDS_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
RAW = DATA / "raw"                                      # untouched API responses (cache)
PROC = DATA / "processed"                               # aligned per-match timelines
OUT = DATA / "output"                                   # trades, reports

for _d in (DATA, RAW, RAW / "polymarket", RAW / "oddsapi", PROC, OUT):
    _d.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    # --- data sourcing ---
    odds_api_key: str = field(default_factory=lambda: os.environ.get("ODDS_API_KEY", ""))
    # the-odds-api sport keys (confirm exact keys with validate_data.py / /sports)
    sport_keys: tuple[str, ...] = ("soccer_epl", "soccer_fifa_world_cup")
    regions: str = "eu,uk"                  # eu/uk carry Pinnacle (the sharp benchmark)
    sharp_book: str = "Pinnacle"            # de-vig benchmark; falls back to consensus
    odds_format: str = "decimal"

    # --- time grid / alignment ---
    lookback_hours: float = 12.0            # how long before kickoff we study
    grid_minutes: int = 30                  # sampling step
    snap_minutes: int = 30                  # how often to pull historical odds snapshots

    # --- de-vig ---
    devig_method: str = "shin"              # shin | power | multiplicative

    # --- execution model (tier-1 backtest uses Polymarket mid price) ---
    fee: float = 0.0                        # modelling assumption; configure for a real dataset
    half_spread: float = 0.01               # assumed cost of crossing the book (NO depth history -> assume)
    latency_seconds: float = 20.0           # signal -> on-chain fill delay
    slippage: float = 0.0                   # extra adverse move during latency (added to entry price)

    # --- discovery ---
    # Backtesting needs FINISHED games (known outcomes). True = pull resolved
    # matches; False = upcoming/live markets only.
    include_finished: bool = True

    # --- strategy ---
    edge_threshold: float = 0.03            # min (fair_prob - effective_cost) to trade
    kelly_fraction: float = 0.25            # fractional Kelly
    kelly_cap: float = 0.05                 # max fraction of bankroll per bet
    bankroll: float = 1000.0
    one_bet_per_market: bool = True         # first qualifying signal only

    # --- stats ---
    bootstrap_iters: int = 5000
    rng_seed: int = 7

def load() -> Settings:
    return Settings()
