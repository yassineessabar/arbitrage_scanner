"""
dashboard/top_setups.py — Top opportunity cards.

Renders the top N opportunities as detailed cards with full metrics.
"""

from __future__ import annotations

from typing import List

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


def render_top_setups(
    opportunities: List[Opportunity],
    count: int = 3,
) -> None:
    """Render top opportunity cards in Streamlit.

    Args:
        opportunities: List of Opportunity objects sorted by score.
        count: Number of top setups to display.
    """
    # Filter to only tradeable signals for top display
    top = [
        o for o in opportunities
        if o.signal in (Signal.CASH_AND_CARRY, Signal.REVERSE_CC, Signal.WATCH)
    ][:count]

    if not top:
        st.caption("No active setups.")
        return

    cols = st.columns(min(len(top), count))

    for i, opp in enumerate(top):
        b = opp.basis_result
        color = signal_color(opp.signal.value)

        with cols[i]:
            st.markdown(
                f"""
                <div style="
                    border: 1px solid {color};
                    border-radius: 8px;
                    padding: 16px;
                    background: rgba(0,0,0,0.3);
                    margin-bottom: 8px;
                ">
                    <div style="font-size: 12px; color: #999;">#{i+1} SETUP — {b.timestamp.strftime('%H:%M:%S UTC') if b.timestamp else ''}</div>
                    <div style="font-size: 20px; font-weight: bold; color: white;">
                        {b.asset} — {b.exchange.capitalize()}
                    </div>
                    <hr style="border-color: #333; margin: 8px 0;">
                    <div style="font-size: 13px; color: #ccc;">
                        Spot: <b>{fmt_price(b.spot_mid)}</b> USDT<br>
                        Futures: <b>{fmt_price(b.futures_mid)}</b> USDT
                        ({b.expiry.strftime('%b %d') if b.expiry else 'PERP'})<br>
                        DTE: <b>{fmt_dte(b.days_to_expiry)}</b>
                    </div>
                    <hr style="border-color: #333; margin: 8px 0;">
                    <div style="font-size: 13px; color: #ccc;">
                        Basis: <b>{fmt_basis(b.basis_abs)}</b> ({fmt_pct(b.basis_pct)})<br>
                        Annualized: <b>{fmt_pct(b.annualized_basis)}</b><br>
                        Net Edge: <b>{fmt_pct(b.annualized_net_edge_cc if b.annualized_net_edge_cc else b.net_edge_cc_pct)}</b>
                    </div>
                    <hr style="border-color: #333; margin: 8px 0;">
                    <div style="font-size: 13px; color: #ccc;">
                        Volume: <b>{fmt_volume(b.volume_usd_24h)}</b><br>
                        Spread: <b>{fmt_pct(b.spread_pct, 3)}</b>
                    </div>
                    <hr style="border-color: #333; margin: 8px 0;">
                    <div style="color: {color}; font-weight: bold; font-size: 14px;">
                        {opp.signal.value}
                    </div>
                    <div style="font-size: 24px; font-weight: bold; color: {color};">
                        {fmt_score(opp.score)} / 100
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
