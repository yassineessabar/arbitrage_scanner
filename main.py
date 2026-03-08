"""
main.py — System entry point for the V1 Institutional Crypto Arbitrage Scanner.

Orchestrates:
  1. Config initialization
  2. Structured logging setup
  3. Connector startup (Binance, Bybit, OKX)
  4. Market data store
  5. Periodic scan loop (basis, filter, score, rank)
  6. Dashboard state output
  7. Storage persistence
  8. Graceful shutdown (SIGINT/SIGTERM)

Usage:
    python main.py
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

import structlog

from config.settings import Settings, get_settings
from connectors.binance import BinanceConnector
from connectors.bybit import BybitConnector
from connectors.okx import OKXConnector
from connectors.base import BaseConnector
from normalization.normalizer import normalize_quote
from normalization.schema import Opportunity, Signal
from market_data.store import MarketDataStore
from market_data.aggregator import aggregate_pairs
from arbitrage.basis import compute_basis
from arbitrage.pairs import PairManager
from scoring.ranker import rank_opportunities
from storage.writer import StorageWriter
from simulation.engine import SimulationEngine
from simulation.cross_exchange import CrossExchangeEngine
from utils.logger import setup_logging

logger = structlog.get_logger(__name__)

# Dashboard state file path
DASHBOARD_STATE_PATH = os.path.join(
    os.path.dirname(__file__), "data", "dashboard_state.json"
)


class ArbitrageScanner:
    """Main orchestrator for the arbitrage scanning system.

    Manages connector lifecycle, scan loop, scoring, storage, and
    dashboard state output.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._store = MarketDataStore()
        self._pair_manager = PairManager()
        self._writer = StorageWriter(settings)
        self._connectors: Dict[str, BaseConnector] = {}
        self._connector_tasks: List[asyncio.Task] = []
        self._running = False
        self._latest_opportunities: List[Opportunity] = []
        self._sim_engine: Optional[SimulationEngine] = None
        if settings.simulation.enabled:
            self._sim_engine = SimulationEngine(settings)
        self._cx_engine: Optional[CrossExchangeEngine] = None
        cx_cfg = getattr(settings, "cross_exchange", None)
        if cx_cfg is not None and cx_cfg.enabled:
            self._cx_engine = CrossExchangeEngine(settings)

    async def start(self) -> None:
        """Initialize and start all system components."""
        logger.info("scanner_starting")

        # Initialize storage
        self._writer.initialize()

        # Create connectors for enabled exchanges
        enabled = self._settings.get_enabled_exchanges()
        if "binance" in enabled:
            self._connectors["binance"] = BinanceConnector()
        if "bybit" in enabled:
            self._connectors["bybit"] = BybitConnector()
        if "okx" in enabled:
            self._connectors["okx"] = OKXConnector()

        # Set callbacks and configure symbols
        symbols = [a.symbol for a in self._settings.assets]
        for name, connector in self._connectors.items():
            connector.set_callback(self._on_quote)
            connector._symbols = symbols

        # Start connectors as background tasks
        self._running = True
        for name, connector in self._connectors.items():
            task = asyncio.create_task(
                connector.run(), name=f"connector_{name}"
            )
            self._connector_tasks.append(task)
            logger.info("connector_task_started", exchange=name)

        # Start scan loop
        scan_task = asyncio.create_task(
            self._scan_loop(), name="scan_loop"
        )
        self._connector_tasks.append(scan_task)

        logger.info(
            "scanner_started",
            exchanges=list(self._connectors.keys()),
            assets=symbols,
            scan_interval=self._settings.system.scan_interval_seconds,
        )

        # Wait for all tasks (or cancellation)
        try:
            await asyncio.gather(*self._connector_tasks)
        except asyncio.CancelledError:
            logger.info("scanner_cancelled")

    async def stop(self) -> None:
        """Gracefully stop all components."""
        logger.info("scanner_stopping")
        self._running = False

        # Cancel all tasks
        for task in self._connector_tasks:
            task.cancel()

        # Wait for tasks to finish
        await asyncio.gather(*self._connector_tasks, return_exceptions=True)

        # Stop connectors
        for name, connector in self._connectors.items():
            try:
                await connector.stop()
            except Exception as e:
                logger.debug("connector_stop_error", exchange=name, error=str(e))

        # Close storage
        self._writer.close()
        logger.info("scanner_stopped")

    async def _on_quote(self, exchange_id: str, raw_payload: dict) -> None:
        """Callback for incoming raw quotes from connectors.

        Args:
            exchange_id: Exchange that sent the quote.
            raw_payload: Raw exchange payload.
        """
        quote = normalize_quote(exchange_id, raw_payload)
        if quote is not None:
            await self._store.upsert(quote)

    async def _scan_loop(self) -> None:
        """Periodic scan loop: aggregate pairs, compute basis, filter, score, store."""
        interval = self._settings.system.scan_interval_seconds

        # Wait for initial data
        await asyncio.sleep(interval)

        while self._running:
            try:
                await self._run_scan_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("scan_cycle_error", error=str(e))

            await asyncio.sleep(interval)

    async def _run_scan_cycle(self) -> None:
        """Execute one full scan cycle."""
        # Aggregate pairs from store
        pairs = await aggregate_pairs(
            self._store,
            stale_threshold=self._settings.filters.max_staleness_seconds,
            dead_threshold=30.0,
        )

        if not pairs:
            logger.debug("no_pairs_available")
            self._write_dashboard_state([])
            return

        # Update pair manager
        self._pair_manager.update_pairs(pairs)

        # Compute basis for each pair
        basis_results = []
        for pair in pairs:
            fee = self._settings.get_fee_for_exchange(pair.exchange)
            slippage = self._settings.filters.slippage_assumption
            basis = compute_basis(pair, fee_rate=fee, slippage=slippage)
            basis_results.append(basis)

        # Rank opportunities (includes filtering and scoring)
        opportunities = rank_opportunities(pairs, basis_results, self._settings)
        self._latest_opportunities = opportunities

        # Write to storage
        for opp in opportunities:
            self._writer.write_opportunity(opp)

        # Run basis simulation
        if self._sim_engine is not None:
            self._sim_engine.check_exits(opportunities)
            for opp in opportunities:
                self._sim_engine.process_opportunity(opp)

        # Run cross-exchange simulation
        if self._cx_engine is not None:
            all_quotes = await self._store.get_all()
            cx_opps, cx_rejected = self._cx_engine.scan_all_spreads(all_quotes)
            self._cx_engine.update_rejected(cx_rejected)
            self._cx_engine.check_exits(cx_opps)
            for cx_opp in cx_opps:
                self._cx_engine.process_opportunity(cx_opp)

        # Update dashboard state
        self._write_dashboard_state(opportunities)

        # Log summary
        signals = sum(
            1
            for o in opportunities
            if o.signal in (Signal.CASH_AND_CARRY, Signal.REVERSE_CC)
        )
        logger.info(
            "scan_cycle_complete",
            pairs=len(pairs),
            opportunities=len(opportunities),
            signals=signals,
            top_score=max((o.score for o in opportunities), default=0),
        )

    def _write_dashboard_state(self, opportunities: List[Opportunity]) -> None:
        """Write current state to JSON for the Streamlit dashboard.

        Args:
            opportunities: List of scored opportunities.
        """
        now = datetime.now(timezone.utc)

        # Feed status
        feed_status = {}
        for name, connector in self._connectors.items():
            last_msg = connector.last_message_time
            feed_status[name] = {
                "connected": connector.is_connected,
                "last_message_time": last_msg.isoformat() if last_msg else None,
            }

        feeds_connected = sum(1 for c in self._connectors.values() if c.is_connected)
        feeds_str = " ".join(
            f"{n.upper()}{'✓' if c.is_connected else '✗'}"
            for n, c in self._connectors.items()
        )

        signals = sum(
            1
            for o in opportunities
            if o.signal in (Signal.CASH_AND_CARRY, Signal.REVERSE_CC)
        )

        # Simulation state
        sim_state = {}
        if self._sim_engine is not None:
            sim_state = self._sim_engine.get_state_for_dashboard()

        # Cross-exchange simulation state
        cx_state = {}
        if self._cx_engine is not None:
            cx_state = self._cx_engine.get_state_for_dashboard()

        state = {
            "last_update": now.strftime("%H:%M:%S UTC"),
            "feeds_status": feeds_str,
            "exchanges_connected": feeds_connected,
            "total_opportunities": len(opportunities),
            "active_signals": signals,
            "refresh_interval": self._settings.dashboard.refresh_interval_seconds,
            "feed_status": feed_status,
            "opportunities": [
                opp.model_dump(mode="json") for opp in opportunities
            ],
            "simulation": sim_state,
            "cross_exchange": cx_state,
        }

        try:
            os.makedirs(os.path.dirname(DASHBOARD_STATE_PATH), exist_ok=True)
            with open(DASHBOARD_STATE_PATH, "w") as f:
                json.dump(state, f, default=str)
        except OSError as e:
            logger.error("dashboard_state_write_error", error=str(e))


def main() -> None:
    """Main entry point."""
    # Load settings
    settings = get_settings()

    # Setup logging
    setup_logging(log_level=settings.system.log_level)

    logger.info(
        "initializing",
        exchanges=list(settings.get_enabled_exchanges().keys()),
        assets=[a.symbol for a in settings.assets],
    )

    # Create scanner
    scanner = ArbitrageScanner(settings)

    # Setup graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown_handler(sig: int, frame: object) -> None:
        logger.info("shutdown_signal_received", signal=sig)
        loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(scanner.stop())
        )

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    try:
        loop.run_until_complete(scanner.start())
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
        loop.run_until_complete(scanner.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
