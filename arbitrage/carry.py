"""
arbitrage/carry.py — Annualized carry computation logic.

Annualizes basis and net edge metrics for dated futures.
Perpetual contracts are NOT annualized (no fixed expiry).
"""

from __future__ import annotations

from typing import Optional


def annualize(value: float, days_to_expiry: Optional[float]) -> Optional[float]:
    """Annualize a percentage metric using days to expiry.

    Formula: annualized = value * (365 / days_to_expiry)

    Args:
        value: The percentage value to annualize (e.g. 0.0066 for 0.66%).
        days_to_expiry: Days until futures contract expiry.

    Returns:
        Annualized value, or None if days_to_expiry is None or <= 0.
    """
    if days_to_expiry is None or days_to_expiry <= 0:
        return None
    return value * (365.0 / days_to_expiry)
