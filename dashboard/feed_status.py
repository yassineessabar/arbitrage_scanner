"""
dashboard/feed_status.py — Exchange feed health panel.

Displays connection status, last message time, and quote counts
per exchange.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import streamlit as st

from normalization.schema import InstrumentQuote


def render_feed_status(
    quotes_by_exchange: Dict[str, List[InstrumentQuote]],
    connector_status: Dict[str, bool],
    last_message_times: Dict[str, Optional[datetime]],
) -> None:
    """Render the feed status panel.

    Args:
        quotes_by_exchange: Dict mapping exchange name to list of quotes.
        connector_status: Dict mapping exchange name to connected status.
        last_message_times: Dict mapping exchange name to last message datetime.
    """
    st.subheader("Feed Status")

    exchanges = ["binance", "bybit", "okx"]
    cols = st.columns(len(exchanges))

    now = datetime.now(timezone.utc)

    for i, exchange in enumerate(exchanges):
        connected = connector_status.get(exchange, False)
        quotes = quotes_by_exchange.get(exchange, [])
        last_msg = last_message_times.get(exchange)

        # Connection indicator
        if connected:
            status_icon = ":green_circle:"
            status_text = "CONNECTED"
        else:
            status_icon = ":red_circle:"
            status_text = "DISCONNECTED"

        # Last message age
        if last_msg:
            if last_msg.tzinfo is None:
                last_msg = last_msg.replace(tzinfo=timezone.utc)
            age = (now - last_msg).total_seconds()
            age_text = f"{age:.0f}s ago"
        else:
            age_text = "No data"

        with cols[i]:
            st.markdown(
                f"""
                <div style="
                    border: 1px solid #333;
                    border-radius: 6px;
                    padding: 12px;
                    background: rgba(0,0,0,0.2);
                    text-align: center;
                ">
                    <div style="font-size: 16px; font-weight: bold; color: white;">
                        {exchange.upper()}
                    </div>
                    <div style="font-size: 13px; margin: 4px 0;">
                        {status_icon} {status_text}
                    </div>
                    <div style="font-size: 12px; color: #999;">
                        Quotes: {len(quotes)}<br>
                        Last: {age_text}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
