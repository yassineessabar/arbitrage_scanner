"""
market_data/aggregator.py — Spot/futures pair matching.

Finds all valid SpotFuturesPair combinations from the market data store.
Matches each spot quote to:
  - Nearest dated future (if available)
  - Next dated future (if available)
  - Perpetual future (if available)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

import structlog

from normalization.schema import (
    ContractType,
    InstrumentQuote,
    SpotFuturesPair,
    StalenessStatus,
)
from market_data.store import MarketDataStore
from market_data.staleness import classify_staleness

logger = structlog.get_logger(__name__)


async def aggregate_pairs(
    store: MarketDataStore,
    stale_threshold: float = 5.0,
    dead_threshold: float = 30.0,
) -> List[SpotFuturesPair]:
    """Match spot quotes to futures quotes and return all valid pairs.

    For each (exchange, asset) combination:
      - Find the spot quote
      - Find all futures quotes (dated + perpetual)
      - Create SpotFuturesPair for each valid combination
      - Skip pairs where either leg is DEAD

    Args:
        store: MarketDataStore containing current quotes.
        stale_threshold: Seconds before a quote is STALE.
        dead_threshold: Seconds before a quote is DEAD.

    Returns:
        List of SpotFuturesPair objects.
    """
    all_quotes = await store.get_all()
    now = datetime.now(timezone.utc)

    # Group quotes by (exchange, asset)
    spots: dict[tuple[str, str], InstrumentQuote] = {}
    futures_list: dict[tuple[str, str], list[InstrumentQuote]] = {}

    for q in all_quotes:
        # Update staleness
        status = classify_staleness(q, stale_threshold, dead_threshold, now)
        q.staleness_status = status

        key = (q.exchange, q.asset)

        if q.contract_type == ContractType.SPOT:
            spots[key] = q
        elif q.contract_type in (ContractType.DATED_FUTURE, ContractType.PERPETUAL):
            futures_list.setdefault(key, []).append(q)

    pairs: List[SpotFuturesPair] = []

    for (exchange, asset), spot in spots.items():
        # Skip dead spot quotes
        if spot.staleness_status == StalenessStatus.DEAD:
            continue

        futs = futures_list.get((exchange, asset), [])

        for fut in futs:
            # Skip dead futures quotes
            if fut.staleness_status == StalenessStatus.DEAD:
                continue

            pair_id = _build_pair_id(exchange, asset, fut)
            try:
                pair = SpotFuturesPair(
                    exchange=exchange,
                    asset=asset,
                    spot=spot,
                    futures=fut,
                    pair_id=pair_id,
                    created_at=now,
                )
                pairs.append(pair)
            except ValueError as e:
                logger.debug(
                    "pair_validation_failed",
                    exchange=exchange,
                    asset=asset,
                    error=str(e),
                )

    logger.debug("pairs_aggregated", count=len(pairs))
    return pairs


def _build_pair_id(
    exchange: str, asset: str, futures: InstrumentQuote
) -> str:
    """Build a unique pair identifier.

    Args:
        exchange: Exchange identifier.
        asset: Base asset symbol.
        futures: Futures InstrumentQuote.

    Returns:
        Pair ID string (e.g. 'binance_BTC_20250627' or 'binance_BTC_PERP').
    """
    if futures.contract_type == ContractType.PERPETUAL:
        return f"{exchange}_{asset}_PERP"
    elif futures.expiry is not None:
        return f"{exchange}_{asset}_{futures.expiry.strftime('%Y%m%d')}"
    else:
        return f"{exchange}_{asset}_UNKNOWN"
