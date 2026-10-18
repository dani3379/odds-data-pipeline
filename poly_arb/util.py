"""Shared helpers: HTTP GET with retry/cache, JSON I/O, time conversions."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# --- time ---
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_unix(dt: datetime) -> int:
    return int(dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp())


def from_unix(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def parse_iso(s: str) -> datetime:
    """Parse ISO8601, tolerating a trailing Z."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- json files ---
def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --- http ---
class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


# Cloudflare 403s Python's default UA; present a browser UA (real, observed need).
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def http_get(url: str, params: dict | None = None, retries: int = 3,
             backoff: float = 1.5, timeout: int = 40) -> tuple[Any, dict]:
    """GET -> (parsed_json, response_headers). Retries on 429/5xx."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                return json.loads(raw), dict(r.headers)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = backoff ** attempt
                log(f"  HTTP {e.code}, retry in {wait:.1f}s")
                time.sleep(wait)
                last = HttpError(e.code, body)
                continue
            raise HttpError(e.code, body)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(backoff ** attempt)
                last = e
                continue
            raise
    if last:
        raise last
    raise RuntimeError("unreachable")


def cached_get(cache_path: Path, url: str, params: dict | None = None) -> Any:
    """http_get with a disk cache so re-runs don't re-hit (or re-bill) the API."""
    if cache_path.exists():
        return load_json(cache_path)
    data, _ = http_get(url, params)
    save_json(cache_path, data)
    return data
