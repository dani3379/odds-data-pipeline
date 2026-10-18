# Odds Data Pipeline

A Python case study in collecting API data, aligning time series, generating statistical reports, and simulating execution. The included demonstration runs entirely on generated inputs, without API keys or internet access.

This project illustrates the engineering behind a research workflow. Its synthetic market deliberately contains lag and mispricing; the resulting metrics are **not evidence of a profitable trading strategy**.

## What it demonstrates

- Separate adapters for match metadata, price histories, and bookmaker odds.
- Cached JSON ingestion and team/market matching.
- As-of timestamp alignment that uses the latest observation available at each decision time.
- Multiplicative, power, and Shin methods for normalizing bookmaker probabilities.
- Calibration summaries, lead/lag analysis, and bootstrap intervals clustered by match-week.
- A paper execution model with spread/fee assumptions, order-book walking, partial fills, and simplified maker queues.
- SQLite fill summaries and partitioned Parquet recording.

These components can support custom API integrations, data cleaning, time-series analysis, simulation, and reporting work. This repository is a personal research demonstration, not evidence of a commissioned client project.

## Setup

Use Python 3.10 or newer. Python 3.12 is used for the local verification described in `docs/VALIDATION.md`.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python run.py demo
.venv\Scripts\python -m pytest -q
```

On macOS/Linux, replace `.venv\Scripts\python` with `.venv/bin/python`. Dependency installation requires internet access; the demo and test suite do not.

## Offline demonstration

```text
python run.py demo
```

The command generates 200 synthetic matches using seed 7 and a fixed scenario date. It produces:

- `data/processed/matches.json`: generated aligned timelines.
- `data/output/trades.json`: simulated decisions and outcomes.
- `data/output/report.json`: calibration, lead/lag, and bootstrap summaries.

Generated data is ignored by Git. Set `ODDS_DATA_DIR` to place outputs elsewhere, for example:

```powershell
$env:ODDS_DATA_DIR = "./demo-output"
python run.py demo
```

The test suite blocks network calls and includes an end-to-end CLI check that writes to a temporary directory. A fixed seed and scenario date make the generated inputs repeatable. Exact numerical output can vary across dependency versions.

## Architecture

```text
API adapters / synthetic generator
            -> cached JSON bundles
            -> linking and as-of alignment
            -> simulation and statistical reports

Optional market-data polling -> recorder -> paper broker -> SQLite/Parquet
```

The reusable package is `poly_arb/`. `run.py` exposes the historical-data pipeline. `run_live.py` exposes optional market-data recording and paper simulation; it does not submit real orders.

## Optional external data

`discover`, `fetch`, `cadence`, `pipeline`, and `run_live.py` make network requests when explicitly invoked. They were not used during local verification. Provider schemas, coverage, fees, and availability need checking before using a real dataset. Historical odds requests may consume paid API credits.

The Odds API adapter reads `ODDS_API_KEY` from the environment. No key is required for the offline demo. Supply credentials through your environment and keep generated data private. No API responses, original cached datasets, account configuration, or local databases are distributed here.

## Limits

- Historical simulation uses a price plus assumed costs, not historical executable depth. The `latency_seconds` setting is descriptive; it does not implement a latency replay.
- Paper fills and queues are approximations, not a reproduction of exchange matching rules. The broker has no account funding, collateral, or real-order execution model.
- Fuzzy team matching and stale observations need dataset-specific review. A timestamp join alone does not establish that a source was available without delay.
- Lead/lag association and bootstrap intervals do not establish causation or a deployable forecasting advantage. Synthetic outcomes validate examples of plumbing and arithmetic, not live performance.
- The live adapters were inspected but not tested against current provider APIs.

See [validation](docs/VALIDATION.md) for the checks actually run and [provenance](PROVENANCE.md) for the source and publication limitations. No software license has been added because the recovered project did not include one.
