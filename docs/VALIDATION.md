# Local validation

The source copy was reviewed for executable import-time behavior and credential-like literals before running tests. The original archived projects were not modified.

Verified on 18 October 2026 with Windows and Python 3.12.4. Direct dependency versions were NumPy 2.5.4, pandas 3.0.6, PyArrow 26.0.0, and pytest 9.1.1. These versions are recorded in `requirements-verified.txt`; this records the tested direct dependencies rather than a complete transitive lockfile.

From the project directory:

```text
python -m pytest -q -p no:cacheprovider
python run.py demo
```

Results:

- **21 tests passed**: 19 recovered tests for probability normalization, sizing/settlement, statistics, linking/alignment, cadence deduplication, fills, positions, SQLite, and Parquet; plus two regression checks for seeded inputs and the offline CLI workflow.
- The demo exited successfully, generating 200 synthetic match timelines, 134 simulated decisions, and JSON reports. It recovered the one-step lag deliberately embedded in the synthetic generator.
- The CLI regression check runs in a child process with socket connections and HTTP opening blocked, and checks the generated report files in a temporary output directory.
- The pytest suite also blocks network access. No external API call, live recording session, real trade, or paid request was made.

The test results establish the behavior covered by these cases on this environment. They do not validate all statistical assumptions, paper-broker edge cases, live API compatibility, financial returns, or installation on other operating systems. The generated market intentionally includes mispricing and lag, so its outcomes are not a trading-performance claim.
