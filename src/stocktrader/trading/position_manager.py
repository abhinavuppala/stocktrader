from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from uuid import uuid4

from stocktrader.trading.models import (
    Order,
    OrderSide,
    OrderType,
    PortfolioSnapshot,
    RebalanceDecision,
)

_QUANTITY_PLACES = Decimal("0.000001")  # 6 decimal places


class PositionManager:
    """Converts a RebalanceDecision into a list of Orders to submit to the broker."""

    def __init__(self, min_trade_value: Decimal = Decimal("1.00")) -> None:
        self._min_trade_value = min_trade_value

    def generate_orders(
        self,
        decision: RebalanceDecision,
        portfolio: PortfolioSnapshot,
        prices: dict[str, Decimal],
    ) -> list[Order]:
        """Generate orders to move the portfolio toward the target weights.

        Args:
            decision: Target weights for each ticker.
            portfolio: Current portfolio snapshot (positions + cash).
            prices: Current price for each ticker that is either held or targeted.

        Returns:
            List of BUY / SELL orders.  The caller is responsible for submission.

        Raises:
            ValueError: If a currently-held ticker is missing from ``prices``.
        """
        # --- 1. Validate prices for all current positions -----------------------
        for position in portfolio.positions:
            if position.ticker not in prices:
                raise ValueError(
                    f"No price provided for currently-held ticker '{position.ticker}'"
                )

        # --- 2. Compute total portfolio value -----------------------------------
        position_value = sum(
            position.quantity * prices[position.ticker]
            for position in portfolio.positions
        )
        total_value: Decimal = portfolio.cash + position_value

        # --- 3. Build a map of current dollar values ----------------------------
        current_dollars: dict[str, Decimal] = {
            position.ticker: position.quantity * prices[position.ticker]
            for position in portfolio.positions
        }

        # --- 4. Determine all tickers we need to consider -----------------------
        # Combine target tickers (excluding CASH) with tickers we currently hold.
        target_tickers: set[str] = {
            ticker for ticker in decision.targets if ticker.upper() != "CASH"
        }
        held_tickers: set[str] = {p.ticker for p in portfolio.positions}
        all_tickers = target_tickers | held_tickers

        # --- 5. Generate orders -------------------------------------------------
        orders: list[Order] = []

        for ticker in all_tickers:
            target_weight = decision.targets.get(ticker, 0.0)
            target_dollars = total_value * Decimal(str(target_weight))
            cur_dollars = current_dollars.get(ticker, Decimal("0"))

            delta = target_dollars - cur_dollars  # positive → need to buy more

            if abs(delta) < self._min_trade_value:
                continue  # noise trade — skip

            price = prices.get(ticker)
            if price is None:
                # Ticker is in targets but not priced — skip (cannot trade).
                # This can happen if a brand-new ticker has no price feed yet.
                # Raise only for currently-held tickers (already validated above).
                continue

            raw_quantity = abs(delta) / price
            quantity = raw_quantity.quantize(_QUANTITY_PLACES, rounding=ROUND_DOWN)

            if quantity <= Decimal("0"):
                continue

            side = OrderSide.BUY if delta > Decimal("0") else OrderSide.SELL

            orders.append(
                Order(
                    order_id=uuid4(),
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    order_type=OrderType.MARKET,
                    created_at=datetime.now(UTC),
                )
            )

        return orders
