"""
filters/edge.py — Net edge after fees/slippage filter.

Rejects opportunities where neither cash-and-carry nor reverse CC
has a positive net edge, and where annualized basis is below minimum.
"""

from __future__ import annotations

from normalization.schema import BasisResult, ContractType, FilterResult


def filter_edge(
    basis: BasisResult,
    min_annualized_basis: float = 0.05,
    min_days_to_expiry: float = 1.0,
) -> FilterResult:
    """Reject if net edge is non-positive or annualized basis is too low.

    Args:
        basis: BasisResult with computed net edges.
        min_annualized_basis: Minimum annualized basis for dated futures (5% = 0.05).
        min_days_to_expiry: Minimum days to expiry (avoid expiry-day risk).

    Returns:
        FilterResult with pass/fail.
    """
    # Check days to expiry for dated futures
    if basis.contract_type == ContractType.DATED_FUTURE:
        dte = basis.days_to_expiry
        if dte is not None and dte < min_days_to_expiry:
            return FilterResult(
                filter_name="edge",
                passed=False,
                reason=f"DTE {dte:.1f} below minimum {min_days_to_expiry:.1f}",
                value=dte,
                threshold=min_days_to_expiry,
            )

    # Check net edge — use gross edge (before costs) for perpetuals since
    # perp basis is inherently small and costs dominate. For dated futures,
    # require positive net edge after costs.
    best_net_edge = max(basis.net_edge_cc_pct, basis.net_edge_rcc_pct)
    best_gross_edge = max(basis.gross_edge_cc_pct, basis.gross_edge_rcc_pct)

    if basis.contract_type == ContractType.PERPETUAL:
        # For perps: pass if gross edge is positive (basis exists in a tradeable direction)
        if best_gross_edge <= 0:
            return FilterResult(
                filter_name="edge",
                passed=False,
                reason=f"No positive gross edge (best={best_gross_edge:.4%})",
                value=best_gross_edge,
                threshold=0.0,
            )
    else:
        # For dated futures: require positive net edge after costs
        if best_net_edge <= 0:
            return FilterResult(
                filter_name="edge",
                passed=False,
                reason=f"No positive net edge (best={best_net_edge:.4%})",
                value=best_net_edge,
                threshold=0.0,
            )

    # Check annualized basis for dated futures
    if basis.contract_type == ContractType.DATED_FUTURE:
        ann = basis.annualized_basis
        if ann is not None and abs(ann) < min_annualized_basis:
            return FilterResult(
                filter_name="edge",
                passed=False,
                reason=f"Annualized basis {ann:.4%} below min {min_annualized_basis:.4%}",
                value=ann,
                threshold=min_annualized_basis,
            )

    return FilterResult(
        filter_name="edge",
        passed=True,
        value=best_net_edge,
        threshold=0.0,
    )
