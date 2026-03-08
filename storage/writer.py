"""
storage/writer.py — Async write logic for basis observations and feed health.

Writes to SQLite on a time interval OR significant basis change.
Uses aiosqlite for non-blocking database access.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import structlog

from normalization.schema import Opportunity
from config.settings import Settings

logger = structlog.get_logger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_INSERT_OBSERVATION = """
INSERT INTO basis_observations (
    timestamp, exchange, asset, spot_symbol, futures_symbol,
    contract_type, expiry_date, days_to_expiry,
    spot_bid, spot_ask, spot_mid,
    futures_bid, futures_ask, futures_mid,
    basis_abs, basis_pct, annualized_basis,
    net_edge_cc_pct, annualized_net_edge_cc,
    signal, score, volume_usd_24h, spread_pct
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_HEALTH = """
INSERT INTO feed_health_log (timestamp, exchange, event_type, details)
VALUES (?, ?, ?, ?)
"""


class StorageWriter:
    """SQLite writer for basis observations and feed health events.

    Implements write throttling: only writes when sufficient time has
    elapsed or basis has changed significantly since last write.
    """

    def __init__(self, settings: Settings) -> None:
        self._db_path = settings.system.storage_path
        self._write_interval = settings.storage.write_interval_seconds
        self._change_threshold_bps = settings.storage.basis_change_threshold_bps
        self._conn: Optional[sqlite3.Connection] = None
        self._last_written: Dict[str, datetime] = {}
        self._last_basis: Dict[str, float] = {}

    def initialize(self) -> None:
        """Create database and tables if they don't exist."""
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        schema_sql = _SCHEMA_PATH.read_text()
        self._conn.executescript(schema_sql)
        self._conn.commit()
        logger.info("storage_initialized", db_path=self._db_path)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def write_opportunity(self, opportunity: Opportunity) -> bool:
        """Write an opportunity to the database if write conditions are met.

        Write conditions (either triggers a write):
          1. Time since last write > write_interval_seconds
          2. Basis change > basis_change_threshold_bps

        Args:
            opportunity: Scored Opportunity to potentially persist.

        Returns:
            True if a write occurred, False if throttled.
        """
        if self._conn is None:
            logger.warning("storage_not_initialized")
            return False

        basis = opportunity.basis_result
        pair_id = opportunity.pair.pair_id
        now = datetime.now(timezone.utc)

        # Check write conditions
        should_write = self._should_write(pair_id, basis.basis_pct, now)
        if not should_write:
            return False

        try:
            self._conn.execute(
                _INSERT_OBSERVATION,
                (
                    basis.timestamp.isoformat(),
                    basis.exchange,
                    basis.asset,
                    basis.spot_symbol,
                    basis.futures_symbol,
                    basis.contract_type.value,
                    basis.expiry.isoformat() if basis.expiry else None,
                    basis.days_to_expiry,
                    basis.spot_bid,
                    basis.spot_ask,
                    basis.spot_mid,
                    basis.futures_bid,
                    basis.futures_ask,
                    basis.futures_mid,
                    basis.basis_abs,
                    basis.basis_pct,
                    basis.annualized_basis,
                    basis.net_edge_cc_pct,
                    basis.annualized_net_edge_cc,
                    basis.signal.value,
                    opportunity.score,
                    basis.volume_usd_24h,
                    basis.spread_pct,
                ),
            )
            self._conn.commit()

            # Update tracking
            self._last_written[pair_id] = now
            self._last_basis[pair_id] = basis.basis_pct

            logger.debug(
                "observation_written",
                pair_id=pair_id,
                score=opportunity.score,
            )
            return True

        except sqlite3.Error as e:
            logger.error("storage_write_error", pair_id=pair_id, error=str(e))
            return False

    def write_feed_health(
        self,
        exchange: str,
        event_type: str,
        details: str = "",
    ) -> None:
        """Log a feed health event.

        Args:
            exchange: Exchange identifier.
            event_type: One of CONNECT, DISCONNECT, RECONNECT, ERROR, STALE.
            details: Additional event details.
        """
        if self._conn is None:
            return

        try:
            now = datetime.now(timezone.utc)
            self._conn.execute(
                _INSERT_HEALTH,
                (now.isoformat(), exchange, event_type, details),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error("health_write_error", exchange=exchange, error=str(e))

    def _should_write(
        self, pair_id: str, current_basis: float, now: datetime
    ) -> bool:
        """Determine if a write should occur based on time or basis change.

        Args:
            pair_id: Unique pair identifier.
            current_basis: Current basis_pct value.
            now: Current timestamp.

        Returns:
            True if write conditions are met.
        """
        # Always write first observation
        if pair_id not in self._last_written:
            return True

        # Time-based trigger
        last_time = self._last_written[pair_id]
        elapsed = (now - last_time).total_seconds()
        if elapsed >= self._write_interval:
            return True

        # Basis change trigger
        last_basis = self._last_basis.get(pair_id, 0.0)
        change_bps = abs(current_basis - last_basis) * 10000
        if change_bps >= self._change_threshold_bps:
            return True

        return False
