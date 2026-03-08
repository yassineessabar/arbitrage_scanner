"""
utils/math_utils.py — Shared math functions.

Provides common mathematical utilities used across modules.
"""

from __future__ import annotations

import math


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a value between minimum and maximum.

    Args:
        value: Value to clamp.
        minimum: Lower bound.
        maximum: Upper bound.

    Returns:
        Clamped value.
    """
    return max(minimum, min(value, maximum))


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safely divide two numbers, returning default if denominator is zero.

    Args:
        numerator: Top of fraction.
        denominator: Bottom of fraction.
        default: Value to return if denominator is zero or very small.

    Returns:
        Result of division or default.
    """
    if abs(denominator) < 1e-15:
        return default
    return numerator / denominator


def log10_safe(value: float, default: float = 0.0) -> float:
    """Safely compute log10, returning default for non-positive values.

    Args:
        value: Value to take log10 of.
        default: Value to return if input is <= 0.

    Returns:
        log10 of value or default.
    """
    if value <= 0:
        return default
    return math.log10(value)


def bps_to_pct(bps: float) -> float:
    """Convert basis points to a decimal percentage.

    Args:
        bps: Value in basis points (e.g. 50 = 0.50%).

    Returns:
        Decimal percentage (e.g. 0.005).
    """
    return bps / 10000.0


def pct_to_bps(pct: float) -> float:
    """Convert a decimal percentage to basis points.

    Args:
        pct: Decimal percentage (e.g. 0.005 = 50 bps).

    Returns:
        Value in basis points.
    """
    return pct * 10000.0
