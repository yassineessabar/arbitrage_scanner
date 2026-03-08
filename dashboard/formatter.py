"""
dashboard/formatter.py — Number formatting helpers for the dashboard.

Provides consistent formatting for prices, percentages, volumes,
and other numeric values displayed in the scanner UI.
"""

from __future__ import annotations


def fmt_price(value: float, decimals: int = 2) -> str:
    """Format a price with comma separators.

    Args:
        value: Price value.
        decimals: Number of decimal places.

    Returns:
        Formatted string like '64,420.00'.
    """
    return f"{value:,.{decimals}f}"


def fmt_pct(value: float | None, decimals: int = 2) -> str:
    """Format a value as a percentage.

    Args:
        value: Decimal value (0.05 = 5%).
        decimals: Number of decimal places.

    Returns:
        Formatted string like '+5.00%' or 'N/A'.
    """
    if value is None:
        return "N/A"
    pct = value * 100
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.{decimals}f}%"


def fmt_volume(value: float | None) -> str:
    """Format volume with magnitude suffix.

    Args:
        value: Volume in USD.

    Returns:
        Formatted string like '$2.4B' or '$800M'.
    """
    if value is None:
        return "N/A"
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    elif value >= 1e6:
        return f"${value / 1e6:.0f}M"
    elif value >= 1e3:
        return f"${value / 1e3:.0f}K"
    else:
        return f"${value:.0f}"


def fmt_score(value: float) -> str:
    """Format a score as integer.

    Args:
        value: Score 0–100.

    Returns:
        Formatted string like '84'.
    """
    return f"{value:.0f}"


def fmt_dte(value: float | None) -> str:
    """Format days to expiry.

    Args:
        value: Days to expiry.

    Returns:
        Formatted string like '42d' or 'PERP'.
    """
    if value is None:
        return "PERP"
    return f"{value:.0f}d"


def fmt_basis(value: float, decimals: int = 2) -> str:
    """Format basis in USD with sign.

    Args:
        value: Absolute basis in USD.
        decimals: Decimal places.

    Returns:
        Formatted string like '+420.00'.
    """
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.{decimals}f}"


def signal_color(signal_value: str) -> str:
    """Return CSS color for a signal value.

    Args:
        signal_value: Signal string value.

    Returns:
        CSS color string.
    """
    colors = {
        "LONG SPOT / SHORT FUT": "#00cc66",   # Green
        "SHORT SPOT / LONG FUT": "#ff4444",    # Red
        "WATCH": "#ffcc00",                     # Yellow
        "NO TRADE": "#888888",                  # Gray
    }
    return colors.get(signal_value, "#888888")
