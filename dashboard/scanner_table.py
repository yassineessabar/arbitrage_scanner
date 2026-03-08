"""
dashboard/scanner_table.py — Main ranked opportunities table.

Renders the full scanner table with all columns, color-coded signals,
and sortable by score.
"""

from __future__ import annotations

from typing import List

import pandas as pd
import streamlit as st

from normalization.schema import Opportunity, Signal
from dashboard.formatter import (
    fmt_basis,
    fmt_dte,
    fmt_pct,
    fmt_price,
    fmt_score,
    fmt_volume,
    signal_color,
)


def render_scanner_table(opportunities: List[Opportunity]) -> None:
    """Render the full scanner table in Streamlit.

    Args:
        opportunities: List of Opportunity objects sorted by score.
    """
    if not opportunities:
        st.info("No opportunities detected yet. Waiting for data...")
        return

    rows = []
    for opp in opportunities:
        b = opp.basis_result
        rows.append({
            "Time": b.timestamp.strftime("%H:%M:%S") if b.timestamp else "",
            "Symbol": b.asset,
            "Exchange": b.exchange.capitalize(),
            "Spot": fmt_price(b.spot_mid),
            "Futures": fmt_price(b.futures_mid),
            "Expiry": b.expiry.strftime("%b-%d") if b.expiry else "PERP",
            "DTE": fmt_dte(b.days_to_expiry),
            "Basis": fmt_basis(b.basis_abs),
            "Basis %": fmt_pct(b.basis_pct),
            "Ann %": fmt_pct(b.annualized_basis),
            "Net %": fmt_pct(b.annualized_net_edge_cc if b.annualized_net_edge_cc is not None else b.net_edge_cc_pct),
            "Volume": fmt_volume(b.volume_usd_24h),
            "Spread": fmt_pct(b.spread_pct, 3),
            "Score": fmt_score(opp.score),
            "Signal": opp.signal.value,
        })

    df = pd.DataFrame(rows)

    # Apply signal color styling
    def _color_signal(val: str) -> str:
        color = signal_color(val)
        return f"color: {color}; font-weight: bold"

    def _color_score(val: str) -> str:
        try:
            s = float(val)
        except ValueError:
            return ""
        if s >= 80:
            return "color: #00cc66; font-weight: bold"
        elif s >= 60:
            return "color: #66cc66"
        elif s >= 40:
            return "color: #ffcc00"
        else:
            return "color: #888888"

    styled = df.style.map(_color_signal, subset=["Signal"])
    styled = styled.map(_color_score, subset=["Score"])

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=min(len(rows) * 40 + 50, 600),
    )
