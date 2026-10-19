# Odds Data Pipeline

A Python portfolio project that turns timestamped observations into inspectable research outputs: aligned timelines, simulated decisions, and statistical reports. It brings together API adapter code, data matching, probability calculations, and local paper-execution models.

The verified demonstration uses generated data and runs without API keys or internet access. It is a useful sample for API integrations, time-series processing, analysis automation, and custom simulation work. The synthetic inputs deliberately contain lag and mispricing; their results do not demonstrate live trading performance or profitability.

## Implemented work

| Component | What the code does | Verification scope |
|---|---|---|
| Data adapters | Requests market metadata, price histories, and bookmaker odds; caches JSON responses. | Source inspected; current external APIs were not exercised. |
| Matching and alignment | Links team/market records and looks up the most recent observation at or before a grid timestamp. | Synthetic raw-bundle/build fixtures; source review. |
| Probability and statistics | Multiplicative/power/Shin normalization, calibration summaries, lead/lag analysis, and match-week clustered bootstrap intervals. | Offline tests and generated examples. |
| Historical simulation | Applies an edge threshold, fractional sizing, assumed costs, and outcome settlement. | Offline arithmetic/build tests; generated scenario. |
| Paper execution and storage | Walks order-book snapshots, models partial fills and simplified maker queues, tracks virtual positions, and writes SQLite/Parquet records. | Targeted offline fixtures; no live session. |

This is a personal research demonstration. It does not represent a commissioned client project or a production trading service.

## Setup

The tested environment is Windows with Python 3.12.4. Dependency declarations are in `requirements.txt` and `requirements-dev.txt`; `requirements-verified.txt` records the tested direct versions rather than a complete transitive lockfile.

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

The command generates 200 synthetic matches using seed 7 and a fixed scenario date, then runs simulation and reporting over those generated, already-aligned timelines. It produces:

- `data/processed/matches.json`: generated aligned timelines.
- `data/output/trades.json`: simulated decisions and outcomes.
- `data/output/report.json`: calibration, lead/lag, and bootstrap summaries.

Generated data is ignored by Git. Set `ODDS_DATA_DIR` to place outputs elsewhere, for example:

```powershell
$env:ODDS_DATA_DIR = "./demo-output"
python run.py demo
```

The demo does not call the external adapters or build timelines from live API responses. Separate fixture tests cover linking and raw-bundle alignment. A fixed seed and scenario date make the generated inputs repeatable; exact numerical output can vary across dependency versions.

## Checks completed

On 20 October 2026, the existing **21 offline tests passed**. They cover selected normalization, cost/sizing/settlement, calibration/bootstrap, matching/building, cadence deduplication, fill/position, SQLite, Parquet, and reproducibility cases. The CLI test runs the demo in a child process with socket connections and HTTP opening blocked and checks its generated report files.

These checks establish the covered examples, not exhaustive statistical, broker, platform, or integration correctness. The suite's network guard blocks its socket/HTTP access; no real API request, trade, or paid service call was part of this audit. The earlier preparation run and its environment details are recorded in [validation notes](docs/VALIDATION.md).

## Architecture

```text
API adapters / synthetic generator
            -> cached JSON bundles
            -> linking and as-of alignment
            -> simulation and statistical reports

Optional market-data polling -> recorder -> paper broker -> SQLite/Parquet
```

The reusable package is `poly_arb/`. `run.py` exposes the historical-data pipeline. `run_live.py` contains optional market-data polling, recording, and paper simulation. Orders are local Python objects; the repository has no exchange login, wallet signing, or real-order submission workflow.

## Optional external data

`discover`, `fetch`, `cadence`, `pipeline`, and `run_live.py` make network requests when explicitly invoked. They were not used during local verification. Provider schemas, coverage, fees, and availability need checking before using a real dataset. Historical odds requests may consume paid API credits.

The Odds API adapter reads `ODDS_API_KEY` from the environment. No key is required for the offline demo. Supply credentials through your environment and keep generated data private. No API responses, original cached datasets, account configuration, or local databases are distributed here.

## Limits

- Historical simulation uses a price plus assumed costs, not historical executable depth. The `latency_seconds` setting is descriptive; it does not implement a latency replay.
- Paper fills and queues are approximations. Each strategy uses snapshots independently; liquidity is not depleted across competing simulated orders. The broker has no account funding, collateral, or exchange risk-control model. Repeated-fill/order-accounting edge cases need further validation.
- Historical sizing uses the configured bankroll for each qualifying market, without a shared cash/margin ledger or portfolio-wide capital constraint.
- Fuzzy team matching and stale observations need dataset-specific review. A timestamp join alone does not establish that a source was available without delay.
- Lead/lag association and bootstrap intervals do not establish causation or a deployable forecasting advantage. Synthetic outcomes validate examples of plumbing and arithmetic, not live performance.
- The live adapters and polling loop were inspected but not tested against current provider APIs. A successful offline demo does not validate current provider authentication, response schemas, prices, or execution conditions.

See [validation](docs/VALIDATION.md) for the checks actually run and [provenance](PROVENANCE.md) for the source and publication limitations. No software license has been added because the recovered project did not include one.
