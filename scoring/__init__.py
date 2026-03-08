"""Scoring package — opportunity scoring and ranking."""

from scoring.ranker import rank_opportunities
from scoring.scorer import compute_score

__all__ = ["compute_score", "rank_opportunities"]
