"""De-vigging: convert raw bookmaker decimal odds -> fair probabilities.

Raw inverse odds sum to >1 (the overround / vig). Naive normalisation
(`multiplicative`) is biased by the favourite-longshot effect; `shin` and
`power` correct for it and are the methods used in the academic literature
(Strumbelj 2014). Works for any number of outcomes (3 for 1X2, 2 for a
Polymarket binary).

All functions take decimal odds (e.g. 2.50) and return probabilities that
sum to 1.0.
"""
from __future__ import annotations

from typing import Sequence


def inverse(odds: Sequence[float]) -> list[float]:
    return [1.0 / o for o in odds]


def booksum(odds: Sequence[float]) -> float:
    """Overround. 1.0 = no vig; 1.05 = 5% margin."""
    return sum(inverse(odds))


def multiplicative(odds: Sequence[float]) -> list[float]:
    pi = inverse(odds)
    s = sum(pi)
    return [p / s for p in pi]


def power(odds: Sequence[float], tol: float = 1e-9) -> list[float]:
    """Find k>=1 s.t. sum(pi_i ** k) == 1, return pi_i ** k."""
    pi = inverse(odds)
    lo, hi = 1.0, 50.0
    for _ in range(200):
        k = 0.5 * (lo + hi)
        s = sum(p ** k for p in pi)
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:        # too much mass -> raise exponent
            lo = k
        else:
            hi = k
    return [p ** k for p in pi]


def shin(odds: Sequence[float], tol: float = 1e-9) -> list[float]:
    """Shin (1993) model with insider proportion z, solved by bisection.

    p_i = ( sqrt(z^2 + 4(1-z) pi_i^2 / S) - z ) / (2(1-z)),  S = sum(pi)
    z chosen so sum(p_i) = 1. Falls back to multiplicative if no root.
    """
    pi = inverse(odds)
    S = sum(pi)

    def probs(z: float) -> list[float]:
        d = 2.0 * (1.0 - z)
        return [(((z * z + 4.0 * (1.0 - z) * (p * p) / S) ** 0.5) - z) / d for p in pi]

    def f(z: float) -> float:
        return sum(probs(z)) - 1.0

    lo, hi = 1e-9, 0.5
    if f(lo) * f(hi) > 0:                # no sign change in range -> bail out
        return multiplicative(odds)
    for _ in range(200):
        z = 0.5 * (lo + hi)
        val = f(z)
        if abs(val) < tol:
            break
        if (val > 0) == (f(lo) > 0):
            lo = z
        else:
            hi = z
    return probs(z)


_METHODS = {"multiplicative": multiplicative, "power": power, "shin": shin}


def devig(odds: Sequence[float], method: str = "shin") -> list[float]:
    if method not in _METHODS:
        raise ValueError(f"unknown devig method {method!r}; choose {list(_METHODS)}")
    p = _METHODS[method](odds)
    s = sum(p)                           # guard against tiny numerical drift
    return [x / s for x in p]
