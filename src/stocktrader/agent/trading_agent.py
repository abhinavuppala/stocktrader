from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from stocktrader.data.models import MarketSnapshot
from stocktrader.trading.models import PortfolioSnapshot, RebalanceDecision


class TradingAgent(Protocol):
    async def decide(
        self,
        portfolio: PortfolioSnapshot,
        market: MarketSnapshot,
    ) -> RebalanceDecision: ...


class MomentumAgent:
    """Rule-based agent: ranks tickers by momentum score, allocates equal
    weight to top N, rest to cash.
    """

    def __init__(
        self,
        universe: list[str],
        top_n: int = 3,
        max_position_pct: float = 0.30,
    ) -> None:
        self._universe = universe
        self._top_n = top_n
        self._max_position_pct = max_position_pct

    async def decide(
        self,
        portfolio: PortfolioSnapshot,
        market: MarketSnapshot,
        scores: dict[str, float] | None = None,
    ) -> RebalanceDecision:
        """Generate a rebalance decision based on momentum scores.

        Args:
            portfolio: Current portfolio snapshot (unused in rule-based logic).
            market: Current market snapshot (unused in rule-based logic).
            scores: Ticker → score mapping. If None, all tickers get equal weight.

        Returns:
            RebalanceDecision with top-N tickers at max_position_pct each.
        """
        if scores is None:
            effective_scores: dict[str, float] = dict.fromkeys(self._universe, 1.0)
        else:
            effective_scores = scores

        # Rank tickers by score descending; tickers not in scores get 0.0
        ranked = sorted(
            self._universe,
            key=lambda t: effective_scores.get(t, 0.0),
            reverse=True,
        )

        top_tickers = ranked[: self._top_n]

        targets: dict[str, float] = dict.fromkeys(top_tickers, self._max_position_pct)

        return RebalanceDecision(
            targets=targets,
            rationale=f"momentum: top {self._top_n} of {len(self._universe)} by score",
            cycle_id=uuid4(),
        )
