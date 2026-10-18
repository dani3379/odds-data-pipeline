"""Regression checks for the public, repeatable offline demonstration."""
import json
import os
from pathlib import Path
import subprocess
import sys

from poly_arb.synth import make_dataset


def test_seeded_inputs_are_repeatable():
    assert make_dataset(n=5, seed=7) == make_dataset(n=5, seed=7)
    assert make_dataset(n=5, seed=7) != make_dataset(n=5, seed=8)


def test_cli_demo_produces_reports_without_network(tmp_path):
    project = Path(__file__).resolve().parent.parent
    child = """
import runpy, socket, sys, urllib.request
def blocked(*args, **kwargs):
    raise AssertionError('Network access attempted by offline demo')
socket.socket.connect = blocked
socket.create_connection = blocked
urllib.request.urlopen = blocked
sys.argv = ['run.py', 'demo']
runpy.run_path('run.py', run_name='__main__')
"""
    env = dict(os.environ, ODDS_DATA_DIR=str(tmp_path / "demo-data"))
    result = subprocess.run([sys.executable, "-c", child], cwd=project, env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    output = tmp_path / "demo-data"
    matches = json.loads((output / "processed" / "matches.json").read_text(encoding="utf8"))
    trades = json.loads((output / "output" / "trades.json").read_text(encoding="utf8"))
    report = json.loads((output / "output" / "report.json").read_text(encoding="utf8"))
    assert len(matches) == 200
    assert all(match["league"] == "synthetic" for match in matches)
    assert trades and report["backtest"]["n_trades"] == len(trades)
    assert report["returns_bootstrap"]["n_clusters"] > 1
    assert "do not establish live-market performance" in result.stdout
