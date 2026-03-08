"""
simulation/backtest.py — Historical replay for the P&L simulation.

Replays stored basis observations from SQLite or in-memory opportunity lists
through the SimulationEngine to produce backtest results.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import structlog

from config.settings import Settings
from normalization.schema import (
    BasisResult,
    ContractType,
    FilterResult,
    InstrumentQuote,
    Opportunity,
    Signal,
    SpotFuturesPair,
)
from simulation.engine import SimulationEngine
from simulation.models import SimulationResult

logger = structlog.get_logger(__name__)


def _row_to_opportunity(row: Dict, settings: Settings) -> Optional[Opportunity]:
    """Reconstruct an Opportunity from a basis_observations DB row.

    This builds minimal-but-valid Pydantic objects from stored data.
    """
    try:
        ts = row["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        exchange = row["exchange"]
        asset = row["asset"]
        signal_str = row["signal"]
        score = float(row["score"])

        # Parse contract type and expiry
        ct_str = row.get("contract_type", "DATED_FUTURE")
        try:
            contract_type = ContractType(ct_str)
        except ValueError:
            contract_type = ContractType.DATED_FUTURE

        expiry = row.get("expiry_date")
        if expiry and isinstance(expiry, str):
            expiry = date.fromisoformat(expiry)
        if contract_type in (ContractType.SPOT, ContractType.PERPETUAL):
            expiry = None

        # Prices
        spot_bid = float(row["spot_bid"])
        spot_ask = float(row["spot_ask"])
        spot_mid = float(row["spot_mid"])
        fut_bid = float(row["futures_bid"])
        fut_ask = float(row["futures_ask"])
        fut_mid = float(row["futures_mid"])

        # Build InstrumentQuotes
        spot_quote = InstrumentQuote(
            exchange=exchange,
            raw_symbol=f"{asset}USDT",
            internal_symbol=f"{asset}/USDT SPOT",
            asset=asset,
            contract_type=ContractType.SPOT,
            expiry=None,
            bid=spot_bid,
            ask=spot_ask,
            mid=spot_mid,
            last=spot_mid,
            exchange_timestamp=ts,
            ingest_timestamp=ts,
        )

        fut_symbol = f"{asset}/USDT PERP" if contract_type == ContractType.PERPETUAL else f"{asset}/USDT FUT {expiry}"
        futures_quote = InstrumentQuote(
            exchange=exchange,
            raw_symbol=f"{asset}USDT_FUT",
            internal_symbol=fut_symbol,
            asset=asset,
            contract_type=contract_type,
            expiry=expiry,
            bid=fut_bid,
            ask=fut_ask,
            mid=fut_mid,
            last=fut_mid,
            exchange_timestamp=ts,
            ingest_timestamp=ts,
        )

        pair_id = f"{exchange}_{asset}_{expiry or 'PERP'}"
        pair = SpotFuturesPair(
            exchange=exchange,
            asset=asset,
            spot=spot_quote,
            futures=futures_quote,
            pair_id=pair_id,
            created_at=ts,
        )

        # Parse signal
        try:
            signal = Signal(signal_str)
        except ValueError:
            signal = Signal.NO_TRADE

        # Determine if filters passed based on signal
        passed_filters = signal in (Signal.CASH_AND_CARRY, Signal.REVERSE_CC)

        # Build BasisResult
        basis_abs = float(row["basis_abs"])
        basis_pct = float(row["basis_pct"])
        ann_basis = row.get("annualized_basis")
        if ann_basis is not None:
            ann_basis = float(ann_basis)

        net_edge_cc = float(row.get("net_edge_cc_pct", 0) or 0)
        ann_net_edge_cc = row.get("annualized_net_edge_cc")
        if ann_net_edge_cc is not None:
            ann_net_edge_cc = float(ann_net_edge_cc)

        # Executable basis
        exec_cc = fut_bid - spot_ask
        exec_rcc = spot_bid - fut_ask
        gross_cc = exec_cc / spot_ask if spot_ask > 0 else 0
        gross_rcc = exec_rcc / spot_bid if spot_bid > 0 else 0

        fee_rate = settings.get_fee_for_exchange(exchange)
        slip = settings.filters.slippage_assumption
        total_cost = 2 * fee_rate + 2 * slip
        net_rcc = gross_rcc - total_cost

        # Handle annualization for perpetuals
        if contract_type == ContractType.PERPETUAL:
            ann_basis = None
            ann_net_edge_cc = None
            ann_net_edge_rcc = None
        else:
            ann_net_edge_rcc = None  # We don't store this in DB

        basis_result = BasisResult(
            exchange=exchange,
            asset=asset,
            spot_symbol=spot_quote.internal_symbol,
            futures_symbol=futures_quote.internal_symbol,
            contract_type=contract_type,
            expiry=expiry,
            spot_bid=spot_bid,
            spot_ask=spot_ask,
            spot_mid=spot_mid,
            futures_bid=fut_bid,
            futures_ask=fut_ask,
            futures_mid=fut_mid,
            basis_abs=basis_abs,
            basis_pct=basis_pct,
            annualized_basis=ann_basis,
            executable_basis_cc=exec_cc,
            executable_basis_rcc=exec_rcc,
            gross_edge_cc_pct=gross_cc,
            gross_edge_rcc_pct=gross_rcc,
            net_edge_cc_pct=net_edge_cc,
            net_edge_rcc_pct=net_rcc,
            annualized_net_edge_cc=ann_net_edge_cc,
            annualized_net_edge_rcc=ann_net_edge_rcc,
            signal=signal,
            timestamp=ts,
            volume_usd_24h=float(row.get("volume_usd_24h", 0) or 0),
            spread_pct=float(row.get("spread_pct", 0) or 0),
        )

        opp = Opportunity(
            pair=pair,
            basis_result=basis_result,
            score=score,
            signal=signal,
            passed_filters=passed_filters,
            filter_results=[],
            ranked_at=ts,
        )

        return opp

    except Exception as e:
        logger.debug("row_to_opportunity_failed", error=str(e))
        return None


class BacktestRunner:
    """Runs historical backtests from stored data."""

    @staticmethod
    def run_from_db(db_path: str, settings: Settings) -> SimulationResult:
        """Replay all basis observations from SQLite through the simulation engine.

        Args:
            db_path: Path to the SQLite database.
            settings: System settings.

        Returns:
            SimulationResult with all trades and stats.
        """
        engine = SimulationEngine(settings)

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM basis_observations ORDER BY timestamp ASC"
            )
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
        except sqlite3.Error as e:
            logger.error("backtest_db_error", error=str(e))
            return engine.get_result()

        logger.info("backtest_starting", observations=len(rows))

        # Group rows by timestamp for batch processing
        prev_timestamp = None
        batch: List[Opportunity] = []

        for row in rows:
            opp = _row_to_opportunity(row, settings)
            if opp is None:
                continue

            ts = row["timestamp"]
            if prev_timestamp is not None and ts != prev_timestamp:
                # Process previous batch: check exits then entries
                engine.check_exits(batch)
                for o in batch:
                    engine.process_opportunity(o)
                batch = []

            batch.append(opp)
            prev_timestamp = ts

        # Process final batch
        if batch:
            engine.check_exits(batch)
            for o in batch:
                engine.process_opportunity(o)

        result = engine.get_result()
        logger.info(
            "backtest_complete",
            trades=result.total_trades,
            net_pnl=f"${result.total_net_pnl:,.2f}",
            win_rate=f"{result.win_rate:.1%}",
        )

        return result

    @staticmethod
    def run_from_opportunities(
        opportunities: List[Opportunity], settings: Settings
    ) -> SimulationResult:
        """Replay a list of opportunities through the simulation engine.

        Args:
            opportunities: List of Opportunity objects (sorted by time).
            settings: System settings.

        Returns:
            SimulationResult with all trades and stats.
        """
        engine = SimulationEngine(settings)

        for opp in opportunities:
            engine.check_exits([opp])
            engine.process_opportunity(opp)

        return engine.get_result()
