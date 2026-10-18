> Historical notes preserved from the recovered archive. Setup, external-service claims, and research conclusions below were not independently verified. Use the current repository README and `docs/VALIDATION.md` for the prepared portfolio copy.

# poly_arb — historical odds-movement → Polymarket backtester

Tests whether pre-game **odds movement** (sharp bookmaker line) predicts a
tradeable gap against **Polymarket** prices, for soccer (World Cup + Premier
League). Built for **historical-only** analysis at **≤30-min** granularity — no
live collection required.

## 0. Install & smoke-test (do this first, costs nothing)
```powershell
pip install -r requirements.txt
python tests/test_core.py        # unit tests for the math
python run.py demo               # full pipeline on synthetic data, no keys/network
```
`demo` proves the engine is correct: calibration tracks, lead-lag recovers the
built-in lag, CLV is significant while ROI isn't yet (the honest small-sample
result). Outputs land in `data/output/`.

## Pipeline
```
discover → fetch → build → backtest → report      (or: python run.py pipeline)
```
Each is a `run.py` subcommand; `pipeline` runs them in order. The **engine**
(`build/backtest/report`) is pure and offline-testable; only **fetch** needs
network and (for historical odds) a paid key.

## 1. Validate before paying — `validate_data.py`
```powershell
python validate_data.py --odds-key YOUR_FREE_KEY --snap-per-day 48
```
Confirms (a) which matches Polymarket actually has, (b) Polymarket free price
granularity is ≤30 min, (c) the-odds-api has soccer + Pinnacle, (d) the credit
cost of your scope. **Do not subscribe until every checklist box passes.**

### 1b. Confirm the odds PROGRESSION is real — `run.py cadence`
The whole strategy analyses the **progression** (line movement), not the closing
odds. the-odds-api returns one snapshot per timestamp; the progression is built
by stitching many (`oddsapi.iter_snapshots`). The one thing the free validator
can't check is the archive's **native snapshot cadence** — if it only stored a
snapshot every few hours, a "30-min" pull just returns duplicates. After you have
a key, spend a few credits to measure it:
```powershell
$env:ODDS_API_KEY = "your_key"
python run.py cadence        # walks previous_timestamp, prints real gap minutes
```
If `meets_30min` is false, the progression is too coarse — reconsider before the
full pull. (`iter_snapshots` records each snapshot's *actual* timestamp and
dedupes, so coarse cadence can never masquerade as fine-grained.)

## 2. `discover` (free)
```powershell
python run.py discover
```
Pulls World Cup / Premier League markets from Polymarket Gamma into
`data/processed/pm_markets.json`. Eyeball them — `polymarket._parse_market`
is where you adapt to any API field drift.

## 3. `fetch`  (`python run.py fetch`)
For every market from `discover`, writes a self-contained bundle to
`data/processed/bundles/<condition_id>.json`:
- **Polymarket** (free, always): price history + trade count, cached under
  `data/raw/polymarket/`.
- **Odds** (PAID, only if `ODDS_API_KEY` is set): grid-aligned historical
  snapshots over the pre-game window, pre-filtered to the games matching the
  market's subject team. Each call prints remaining credits; snapshots are
  cached so re-runs never re-bill.

**Safety:** with no key set, fetch pulls only the free Polymarket data — you
cannot bill the odds API by accident. Set the key only after `validate_data.py`
passes:  `$env:ODDS_API_KEY = "your_key"`.

## 4. `build`  (`python run.py build`)
Consumes the bundles via `dataset.build_match_from_bundle` (pure, offline-
tested): links each market to its odds-api game (fuzzy team-name match —
**eyeball the linked count**, extend `ALIASES` for misses), de-vigs the sharp
book (default Shin), and aligns sharp fair prob + Polymarket mid onto a common
grid with **as-of joins (no look-ahead)**. Produces `data/processed/matches.json`
in the same schema `demo` uses.

## 5. `backtest` & `report`
```powershell
python run.py backtest --edge 0.03 --half-spread 0.01
python run.py report
```
- **backtest**: first qualifying signal per market, fractional-Kelly stake,
  explicit cost model, settle on resolution, compute CLV.
- **report**: calibration (Brier + reliability), lead-lag, and **clustered
  bootstrap** CIs for returns and CLV (clusters = match-week).

## Live paper-trader + order-book recorder (`run_live.py`)
Records the live Polymarket order book + trades to `data/live/` (the depth
history that doesn't exist anywhere else) AND races strategies against it with
realistic maker/taker fills — no real money.
```powershell
python run_live.py                 # run continuously (Ctrl-C to stop)
python run_live.py --seconds 120   # short smoke test
python run_live.py --poll 10 --within-hours 24 --taker-fee 0.0 --maker-rebate 0.0
```
- **Realistic fills** (`poly_arb/live/`): taker orders walk the live book for a
  VWAP (partial if thin); maker orders join the queue and fill only as trades
  print through their price — true adverse selection, "would it have filled?"
  answered honestly. Tested in `tests/test_live.py`.
- **Recorder** writes append-only JSONL per token per day → your real dataset.
- **Strategies** (`poly_arb/live/strategies.py`) run side by side (maker vs
  taker, different windows) so you can compare in real conditions.
- Set `--taker-fee` / `--maker-rebate` to Polymarket's current sports schedule.

## Research/analysis scripts (free data)
`study.py` (Polymarket calibration/margin), `momentum.py` (is the move
predictable?), `reversion.py` (fade slow drifts — the lead), `methods.py`
(Hurst/Variance-Ratio/OU half-life + walk-forward/Deflated-Sharpe/PBO rigor).

## Honest limitations (baked into the design)
- **Tier-1 fills.** Historical order-book *depth* isn't retrievable, so fills use
  the historical mid price + an *assumed* `half_spread`/`fee`/`slippage`. Results
  are optimistic on execution until validated with live depth capture.
- **Sample size.** 10–20 PL rounds + World Cup ≈ 150–250 matches: good for
  exploration and **CLV** signal, marginal for *proving* a small ROI edge. Trust
  the clustered bootstrap CI, not the point estimate.
- **Linking is fuzzy.** Always review the team-name matches once per dataset.
- **PL is off-season** until Aug 2026; `discover` reveals whether Polymarket even
  ran per-match PL markets in the rounds you want.

## Layout
```
validate_data.py        pre-purchase data validator (standalone)
run.py                  CLI
poly_arb/
  config.py    settings & paths        devig.py     fair-prob math (shin/power/mult)
  util.py      http/cache/json/time    polymarket.py  Gamma + price/trades (free)
  oddsapi.py   the-odds-api historical dataset.py    linking + grid alignment
  backtest.py  strategy/P&L/CLV        stats.py     calibration/bootstrap/lead-lag
  synth.py     offline self-test data
tests/test_core.py
data/  raw/ (cache)  processed/ (matches)  output/ (trades, report)
```
