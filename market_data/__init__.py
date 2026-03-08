"""Market data package — in-memory store, staleness, and pair aggregation."""

from market_data.aggregator import aggregate_pairs
from market_data.staleness import classify_staleness, get_quote_age_seconds
from market_data.store import MarketDataStore

__all__ = [
    "MarketDataStore",
    "classify_staleness",
    "get_quote_age_seconds",
    "aggregate_pairs",
]
