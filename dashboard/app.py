"""
dashboard/app.py — Main Streamlit entry point for the scanner dashboard.

Run with:
    streamlit run dashboard/app.py

Displays the professional crypto basis scanner UI with auto-refresh.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import streamlit as st
from streamlit_autorefresh import st_autorefresh

# Add project root to path for imports
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config.settings import get_settings
from simulation.demo import run_demo_simulation
from simulation.cross_exchange_demo import run_cross_exchange_demo
from dashboard.simulation_panel import render_simulation_panel
from dashboard.cross_exchange_panel import render_cross_exchange_panel

# ── Page Config ──
st.set_page_config(
    page_title="Crypto Basis Scanner",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Dark Theme CSS ──
st.markdown(
    """
    <style>
    .stApp {
        background-color: #0e1117;
    }
    .scanner-header {
        background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%);
        padding: 16px 24px;
        border-radius: 8px;
        margin-bottom: 16px;
    }
    .scanner-title {
        font-size: 24px;
        font-weight: bold;
        color: #e0e0e0;
    }
    .scanner-subtitle {
        font-size: 13px;
        color: #999;
    }
    .metric-card {
        background: rgba(0,0,0,0.3);
        border: 1px solid #333;
        border-radius: 6px;
        padding: 12px;
        text-align: center;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Shared State File (written by main.py) ──
STATE_FILE = os.path.join(_project_root, "data", "dashboard_state.json")

# Remote VPS config — set these env vars to sync state from a remote server
# Example: SCANNER_VPS_HOST=ubuntu@vps-d62ba235.vps.ovh.net
#          SCANNER_VPS_PASSWORD=yourpassword
#          SCANNER_VPS_PATH=~/arbitrage_scanner/data/dashboard_state.json
VPS_HOST = os.environ.get("SCANNER_VPS_HOST", "")
VPS_PASSWORD = os.environ.get("SCANNER_VPS_PASSWORD", "")
VPS_REMOTE_PATH = os.environ.get(
    "SCANNER_VPS_PATH", "~/arbitrage_scanner/data/dashboard_state.json"
)


def _sync_from_vps() -> bool:
    """Sync dashboard_state.json from remote VPS via scp."""
    if not VPS_HOST or not VPS_PASSWORD:
        return False
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        result = subprocess.run(
            [
                "sshpass", "-p", VPS_PASSWORD,
                "scp", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                f"{VPS_HOST}:{VPS_REMOTE_PATH}",
                STATE_FILE,
            ],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def load_state() -> dict:
    """Load the current scanner state, syncing from VPS if configured."""
    if VPS_HOST:
        _sync_from_vps()
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> None:
    """Main dashboard rendering function."""
    state = load_state()

    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    last_update = state.get("last_update", "N/A")

    # ── Header ──
    st.markdown(
        f"""
        <div class="scanner-header">
            <div class="scanner-title">CRYPTO BASIS SCANNER v1.0</div>
            <div class="scanner-subtitle">
                Last update: {last_update} | Page refreshed: {now_str} |
                Feeds: {state.get('feeds_status', 'N/A')} |
                Opportunities: {state.get('total_opportunities', 0)} |
                Signals: {state.get('active_signals', 0)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Tabs ──
    tab_basis_sim, tab_cross_exchange = st.tabs([
        "Basis Simulation",
        "Cross-Exchange Arb",
    ])

    # ── Tab 1: Basis Simulation ──
    with tab_basis_sim:
        sim_state = state.get("simulation", {})
        # Use live data if scanner is running (has "enabled" key), otherwise demo
        if not sim_state or "enabled" not in sim_state:
            settings = get_settings()
            if settings.simulation.enabled:
                if "demo_sim_state" not in st.session_state:
                    st.session_state.demo_sim_state = run_demo_simulation(settings)
                sim_state = st.session_state.demo_sim_state
                st.caption("DEMO DATA — Start the scanner (`python main.py`) for live simulated P&L")
        # Pass basis opportunities (rejected ones) to the panel
        basis_opps = state.get("opportunities", [])
        render_simulation_panel(sim_state, basis_opps)

    # ── Tab 2: Cross-Exchange Arbitrage ──
    with tab_cross_exchange:
        cx_state = state.get("cross_exchange", {})
        if not cx_state or "enabled" not in cx_state:
            if "demo_cx_state" not in st.session_state:
                st.session_state.demo_cx_state = run_cross_exchange_demo()
            cx_state = st.session_state.demo_cx_state
            st.caption("DEMO DATA — Start the scanner (`python main.py`) for live simulated P&L")
        render_cross_exchange_panel(cx_state)

    # ── Auto-refresh (seamless, no full page reload) ──
    refresh_seconds = state.get("refresh_interval", 15)
    st_autorefresh(interval=refresh_seconds * 1000, key="scanner_refresh")


if __name__ == "__main__":
    main()
