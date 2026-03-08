"""
dashboard/simulation_panel.py — Streamlit panel for P&L simulation results.

Renders equity curve, trade log, open positions, and summary statistics.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from dashboard.formatter import fmt_pct, fmt_price


def render_simulation_panel(sim_state: Dict[str, Any], basis_opps: List[Dict] | None = None) -> None:
    """Render the simulation results panel.

    Args:
        sim_state: Simulation state dict from engine.get_state_for_dashboard().
        basis_opps: Raw opportunity dicts from scanner (includes rejected ones).
    """
    st.subheader("P&L Simulation")

    if not sim_state or not sim_state.get("enabled"):
        st.info("Simulation is disabled. Enable it in config/default.yaml.")
        return

    # ── Summary Metrics ──
    col1, col2, col3, col4, col5, col6 = st.columns(6)

    net_pnl = sim_state.get("total_net_pnl", 0)
    pnl_color = "#00cc66" if net_pnl >= 0 else "#ff4444"

    col1.markdown(
        f"""<div class="metric-card">
        <div style="color:#999;font-size:11px">NET P&L</div>
        <div style="color:{pnl_color};font-size:20px;font-weight:bold">
            {"+" if net_pnl >= 0 else ""}${net_pnl:,.2f}
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    return_pct = sim_state.get("total_return_pct", 0)
    col2.markdown(
        f"""<div class="metric-card">
        <div style="color:#999;font-size:11px">RETURN</div>
        <div style="color:{pnl_color};font-size:20px;font-weight:bold">
            {fmt_pct(return_pct)}
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    win_rate = sim_state.get("win_rate", 0)
    wr_color = "#00cc66" if win_rate >= 0.5 else "#ffcc00"
    col3.markdown(
        f"""<div class="metric-card">
        <div style="color:#999;font-size:11px">WIN RATE</div>
        <div style="color:{wr_color};font-size:20px;font-weight:bold">
            {win_rate:.1%}
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    col4.markdown(
        f"""<div class="metric-card">
        <div style="color:#999;font-size:11px">TRADES</div>
        <div style="color:#e0e0e0;font-size:20px;font-weight:bold">
            {sim_state.get("total_trades", 0)}
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    sharpe = sim_state.get("sharpe_ratio", 0)
    col5.markdown(
        f"""<div class="metric-card">
        <div style="color:#999;font-size:11px">SHARPE</div>
        <div style="color:#e0e0e0;font-size:20px;font-weight:bold">
            {sharpe:.2f}
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    max_dd = sim_state.get("max_drawdown_pct", 0)
    col6.markdown(
        f"""<div class="metric-card">
        <div style="color:#999;font-size:11px">MAX DD</div>
        <div style="color:#ff4444;font-size:20px;font-weight:bold">
            -{max_dd:.2%}
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Secondary Metrics ──
    scol1, scol2, scol3, scol4 = st.columns(4)
    scol1.metric("Initial Capital", f"${sim_state.get('initial_capital', 0):,.0f}")
    scol2.metric("Current Equity", f"${sim_state.get('equity', 0):,.2f}")
    scol3.metric("Total Fees", f"${sim_state.get('total_fees', 0):,.2f}")
    scol4.metric("Total Slippage", f"${sim_state.get('total_slippage', 0):,.2f}")

    # ── Equity Curve ──
    equity_data = sim_state.get("equity_curve", [])
    if len(equity_data) > 1:
        st.markdown("**Equity Curve**")
        try:
            import plotly.graph_objects as go

            timestamps = [e["timestamp"] for e in equity_data]
            equities = [e["equity"] for e in equity_data]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=timestamps,
                y=equities,
                mode="lines",
                line=dict(color="#00cc66", width=2),
                fill="tozeroy",
                fillcolor="rgba(0,204,102,0.1)",
                name="Equity",
            ))
            fig.update_layout(
                template="plotly_dark",
                height=300,
                margin=dict(l=40, r=20, t=20, b=40),
                xaxis_title="Time",
                yaxis_title="Equity ($)",
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            st.line_chart({"equity": [e["equity"] for e in equity_data]})

    # ── Open Positions ──
    open_pos = sim_state.get("open_positions", [])
    if open_pos:
        st.markdown(f"**Open Positions ({len(open_pos)})**")
        for pos in open_pos:
            pos_ts = str(pos.get("entry_time", ""))
            pos_time = pos_ts[5:16].replace("T", " ") if len(pos_ts) > 16 else pos_ts
            st.markdown(
                f"""<div style="background:rgba(0,0,0,0.3);border:1px solid #333;
                border-radius:6px;padding:8px;margin:4px 0">
                <span style="color:#00cc66;font-weight:bold">{pos.get('asset','?')}</span>
                <span style="color:#999"> | {pos.get('exchange','?')} | {pos.get('signal','')} |
                Opened: {pos_time} |
                Entry basis: {fmt_pct(pos.get('entry_basis_pct'))} |
                Size: ${pos.get('position_size_usd',0):,.0f} |
                Score: {pos.get('score_at_entry',0):.0f}</span>
                </div>""",
                unsafe_allow_html=True,
            )

    # ── Trade Log ──
    closed_trades = sim_state.get("closed_trades", [])
    if closed_trades:
        st.markdown(f"**Recent Trades ({len(closed_trades)})**")

        rows = []
        for t in reversed(closed_trades):
            net = t.get("net_pnl", 0)
            color = "#00cc66" if net >= 0 else "#ff4444"
            entry_ts = str(t.get("entry_time", ""))
            entry_str = entry_ts[5:16].replace("T", " ") if len(entry_ts) > 16 else entry_ts
            exit_ts = str(t.get("exit_time", ""))
            exit_str = exit_ts[5:16].replace("T", " ") if len(exit_ts) > 16 else exit_ts
            rows.append(
                f"""<tr>
                <td>{entry_str}</td>
                <td>{exit_str}</td>
                <td>{t.get('asset','')}</td>
                <td>{t.get('exchange','')}</td>
                <td>{t.get('signal','')[:15]}</td>
                <td>{fmt_pct(t.get('entry_basis_pct'))}</td>
                <td>{fmt_pct(t.get('exit_basis_pct'))}</td>
                <td>${t.get('position_size_usd',0):,.0f}</td>
                <td style="color:{color}">{"+" if net >= 0 else ""}${net:,.2f}</td>
                <td>{t.get('exit_reason','')}</td>
                <td>{t.get('hold_days',0):.1f}d</td>
                </tr>"""
            )

        table_html = f"""
        <div style="overflow-x:auto;max-height:400px;overflow-y:auto">
        <table style="width:100%;border-collapse:collapse;font-size:12px;color:#ccc">
        <thead>
        <tr style="border-bottom:1px solid #444;color:#888">
            <th>Entry</th><th>Exit</th><th>Asset</th><th>Exchange</th><th>Signal</th>
            <th>Entry Basis</th><th>Exit Basis</th><th>Size</th>
            <th>Net P&L</th><th>Exit</th><th>Hold</th>
        </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
        </table>
        </div>
        """
        st.markdown(table_html, unsafe_allow_html=True)

    elif sim_state.get("total_trades", 0) == 0 and not open_pos:
        st.info("No trades yet. Waiting for qualifying signals...")

    # ── Detected But Rejected (basis exists but below threshold) ──
    if basis_opps:
        rejected = [o for o in basis_opps if not o.get("passed_filters", True)]
        if rejected:
            st.markdown(f"**Detected Opportunities — Did Not Qualify ({len(rejected)})**")
            rows = []
            for o in rejected:
                br = o.get("basis_result", {})
                net_cc = br.get("net_edge_cc_pct", 0)
                net_rcc = br.get("net_edge_rcc_pct", 0)
                best_edge = max(net_cc, net_rcc)
                edge_color = "#ffcc00" if best_edge > -0.001 else "#ff4444"
                reasons = []
                for fr in o.get("filter_results", []):
                    if not fr.get("passed") and fr.get("reason"):
                        reasons.append(fr["reason"])
                reason_str = "; ".join(reasons) if reasons else br.get("signal", "")

                ts_raw = o.get("timestamp", "")
                ts_str = ts_raw[11:19] if isinstance(ts_raw, str) and len(ts_raw) > 19 else str(ts_raw)
                rows.append(
                    f"""<tr>
                    <td>{ts_str}</td>
                    <td>{br.get('asset','')}</td>
                    <td>{br.get('exchange','')}</td>
                    <td>{fmt_pct(br.get('basis_pct'))}</td>
                    <td style="color:{edge_color}">{fmt_pct(best_edge)}</td>
                    <td>{fmt_pct(br.get('annualized_basis'))}</td>
                    <td>{br.get('signal','')}</td>
                    <td style="color:#888">{reason_str}</td>
                    </tr>"""
                )

            table_html = f"""
            <div style="overflow-x:auto;max-height:300px;overflow-y:auto">
            <table style="width:100%;border-collapse:collapse;font-size:12px;color:#ccc">
            <thead>
            <tr style="border-bottom:1px solid #444;color:#888">
                <th>Time</th><th>Asset</th><th>Exchange</th><th>Basis</th>
                <th>Net Edge</th><th>Ann. Basis</th><th>Signal</th><th>Reason</th>
            </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
            </table>
            </div>
            """
            st.markdown(table_html, unsafe_allow_html=True)
