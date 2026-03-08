"""
arbitrage/pairs.py — Spot/futures pair lifecycle management.

Manages the set of active pairs being tracked by the basis engine.
Provides helpers to identify nearest-expiry, next-expiry, and perpetual
pairs for a given asset/exchange.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import structlog

from normalization.schema import ContractType, SpotFuturesPair

logger = structlog.get_logger(__name__)


class PairManager:
    """Manages active spot/futures pairs for basis computation.

    Tracks all pairs and provides filtered access by exchange, asset,
    and contract type.
    """

    def __init__(self) -> None:
        self._pairs: Dict[str, SpotFuturesPair] = {}

    def update_pairs(self, pairs: List[SpotFuturesPair]) -> None:
        """Replace the current pair set with new pairs.

        Args:
            pairs: List of SpotFuturesPair from the aggregator.
        """
        self._pairs = {p.pair_id: p for p in pairs}
        logger.debug("pairs_updated", count=len(self._pairs))

    def get_all(self) -> List[SpotFuturesPair]:
        """Return all active pairs."""
        return list(self._pairs.values())

    def get_by_exchange(self, exchange: str) -> List[SpotFuturesPair]:
        """Return all pairs for a given exchange."""
        return [p for p in self._pairs.values() if p.exchange == exchange]

    def get_by_asset(self, asset: str) -> List[SpotFuturesPair]:
        """Return all pairs for a given asset across all exchanges."""
        return [p for p in self._pairs.values() if p.asset == asset]

    def get_nearest_dated(
        self, exchange: str, asset: str
    ) -> Optional[SpotFuturesPair]:
        """Return the nearest dated future pair for an exchange/asset.

        Args:
            exchange: Exchange identifier.
            asset: Base asset symbol.

        Returns:
            The SpotFuturesPair with the nearest expiry, or None.
        """
        dated = [
            p
            for p in self._pairs.values()
            if p.exchange == exchange
            and p.asset == asset
            and p.futures.contract_type == ContractType.DATED_FUTURE
            and p.futures.expiry is not None
        ]
        if not dated:
            return None
        return min(dated, key=lambda p: p.futures.expiry)  # type: ignore[arg-type]

    def get_perpetual(
        self, exchange: str, asset: str
    ) -> Optional[SpotFuturesPair]:
        """Return the perpetual pair for an exchange/asset.

        Args:
            exchange: Exchange identifier.
            asset: Base asset symbol.

        Returns:
            The perpetual SpotFuturesPair, or None.
        """
        for p in self._pairs.values():
            if (
                p.exchange == exchange
                and p.asset == asset
                and p.futures.contract_type == ContractType.PERPETUAL
            ):
                return p
        return None

    @property
    def count(self) -> int:
        """Number of active pairs."""
        return len(self._pairs)
