"""Normalization package — raw exchange data to internal schema conversion."""

from normalization.normalizer import normalize_quote
from normalization.schema import (
    BasisResult,
    ContractType,
    FilterResult,
    InstrumentQuote,
    Opportunity,
    Signal,
    SpotFuturesPair,
    StalenessStatus,
)
from normalization.symbol_map import resolve_symbol

__all__ = [
    "normalize_quote",
    "resolve_symbol",
    "BasisResult",
    "ContractType",
    "FilterResult",
    "InstrumentQuote",
    "Opportunity",
    "Signal",
    "SpotFuturesPair",
    "StalenessStatus",
]
