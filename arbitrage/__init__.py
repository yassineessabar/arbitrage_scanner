"""Arbitrage package — basis computation, carry, and pair management."""

from arbitrage.basis import compute_basis
from arbitrage.carry import annualize
from arbitrage.pairs import PairManager

__all__ = ["compute_basis", "annualize", "PairManager"]
