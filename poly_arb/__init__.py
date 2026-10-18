"""poly_arb - historical odds-movement vs Polymarket backtesting toolkit.

Pipeline (each stage is a `run.py` subcommand):
    discover -> fetch -> build -> backtest -> report

The ENGINE (build/backtest/report/stats/devig) is pure and works on an
internal schema, so it runs offline on synthetic data (`run.py demo`).
The FETCH layer (polymarket/oddsapi) is the only part that needs network +
(for historical odds) a paid the-odds-api key. Validate first with
validate_data.py before paying for anything.
"""

__version__ = "0.1.0"
