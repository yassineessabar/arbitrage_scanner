"""
storage/reader.py — Query interface for historical basis data.

Supports:
  - Basis history by pair and exchange
  - Top opportunities in time window
  - Feed health log queries
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class StorageReader:
    """Read-only query interface for the arbitrage scanner database."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def initialize(self) -> None:
        """Open a read-only connection to the database."""
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        logger.info("reader_initialized", db_path=self._db_path)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_basis_history(
        self,
        exchange: str,
        asset: str,
        days: int = 7,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Query basis history for a specific exchange/asset pair.

        Args:
            exchange: Exchange identifier.
            asset: Base asset symbol.
            days: Number of days of history to retrieve.
            limit: Maximum number of rows.

        Returns:
            List of dicts with basis observation data.
        """
        if self._conn is None:
            return []

        query = """
            SELECT timestamp, basis_pct, annualized_basis, net_edge_cc_pct,
                   annualized_net_edge_cc, score, signal, volume_usd_24h, spread_pct
            FROM basis_observations
            WHERE exchange = ? AND asset = ?
              AND timestamp > datetime('now', ?)
            ORDER BY timestamp DESC
            LIMIT ?
        """
        try:
            cursor = self._conn.execute(
                query, (exchange, asset, f"-{days} days", limit)
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("query_error", query="basis_history", error=str(e))
            return []

    def get_top_opportunities(
        self,
        hours: int = 1,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Query top opportunities in a time window.

        Args:
            hours: Number of hours to look back.
            limit: Maximum number of results.

        Returns:
            List of dicts with opportunity data, sorted by score.
        """
        if self._conn is None:
            return []

        query = """
            SELECT *
            FROM basis_observations
            WHERE timestamp > datetime('now', ?)
              AND signal != 'NO TRADE'
            ORDER BY score DESC
            LIMIT ?
        """
        try:
            cursor = self._conn.execute(query, (f"-{hours} hours", limit))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("query_error", query="top_opportunities", error=str(e))
            return []

    def get_feed_health(
        self,
        exchange: Optional[str] = None,
        hours: int = 24,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query feed health events.

        Args:
            exchange: Optional exchange filter.
            hours: Number of hours to look back.
            limit: Maximum number of results.

        Returns:
            List of dicts with feed health event data.
        """
        if self._conn is None:
            return []

        if exchange:
            query = """
                SELECT * FROM feed_health_log
                WHERE exchange = ? AND timestamp > datetime('now', ?)
                ORDER BY timestamp DESC LIMIT ?
            """
            params = (exchange, f"-{hours} hours", limit)
        else:
            query = """
                SELECT * FROM feed_health_log
                WHERE timestamp > datetime('now', ?)
                ORDER BY timestamp DESC LIMIT ?
            """
            params = (f"-{hours} hours", limit)

        try:
            cursor = self._conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("query_error", query="feed_health", error=str(e))
            return []

    def get_all_observations(self, limit: int = 10000) -> List[Dict[str, Any]]:
        """Query all basis observations ordered by timestamp (for backtest replay).

        Args:
            limit: Maximum number of rows.

        Returns:
            List of dicts with all columns from basis_observations.
        """
        if self._conn is None:
            return []

        try:
            cursor = self._conn.execute(
                "SELECT * FROM basis_observations ORDER BY timestamp ASC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("query_error", query="all_observations", error=str(e))
            return []

    def get_observation_count(self) -> int:
        """Return total number of basis observations."""
        if self._conn is None:
            return 0
        try:
            cursor = self._conn.execute("SELECT COUNT(*) FROM basis_observations")
            return cursor.fetchone()[0]
        except sqlite3.Error:
            return 0
