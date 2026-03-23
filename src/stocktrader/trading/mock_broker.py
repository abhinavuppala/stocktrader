from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from stocktrader.trading.broker_interface import IBroker
from stocktrader.trading.models import (
    Fill,
    Order,
    OrderSide,
    PortfolioSnapshot,
    Position,
)


class MockBroker(IBroker):
    """In-memory broker for testing and paper trading simulations.

    Prices are injected via ``set_price`` or a ``price_oracle`` callable.
    Slippage is applied as basis points: buys fill slightly higher, sells
    slightly lower than the mid price.
    """

    def __init__(
        self,
        initial_cash: Decimal,
        slippage_bps: int = 5,
        price_oracle: Callable[[str], Decimal] | None = None,
    ) -> None:
        self._cash: Decimal = initial_cash
        self._slippage_bps: int = slippage_bps
        self._price_map: dict[str, Decimal] = {}
        self._price_oracle: Callable[[str], Decimal] | None = price_oracle
        # ticker -> (quantity, avg_cost)
        self._positions: dict[str, tuple[Decimal, Decimal]] = {}

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def set_price(self, ticker: str, price: Decimal) -> None:
        """Inject a price for *ticker* so that orders can be filled."""
        self._price_map[ticker] = price

    # ------------------------------------------------------------------
    # IBroker implementation
    # ------------------------------------------------------------------

    async def submit_order(self, order: Order) -> Fill:
        mid_price = self._resolve_price(order.ticker)
        slippage_factor = Decimal(self._slippage_bps) / Decimal("10000")

        if order.side is OrderSide.BUY:
            fill_price = mid_price * (Decimal("1") + slippage_factor)
            total_cost = fill_price * order.quantity
            if total_cost > self._cash:
                raise ValueError(
                    f"Insufficient cash: need {total_cost}, have {self._cash}"
                )
            self._cash -= total_cost
            self._apply_buy(order.ticker, order.quantity, fill_price)
        else:
            fill_price = mid_price * (Decimal("1") - slippage_factor)
            self._apply_sell(order.ticker, order.quantity)
            self._cash += fill_price * order.quantity

        return Fill(
            fill_id=uuid4(),
            order_id=order.order_id,
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            filled_at=datetime.now(UTC),
        )

    async def get_positions(self) -> list[Position]:
        return [
            Position(ticker=ticker, quantity=qty, avg_cost=avg_cost)
            for ticker, (qty, avg_cost) in self._positions.items()
            if qty > Decimal("0")
        ]

    async def get_cash(self) -> Decimal:
        return self._cash

    async def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            positions=await self.get_positions(),
            cash=self._cash,
            snapshot_at=datetime.now(UTC),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_price(self, ticker: str) -> Decimal:
        if ticker in self._price_map:
            return self._price_map[ticker]
        if self._price_oracle is not None:
            return self._price_oracle(ticker)
        raise ValueError(f"No price available for ticker '{ticker}'")

    def _apply_buy(self, ticker: str, quantity: Decimal, fill_price: Decimal) -> None:
        if ticker in self._positions:
            existing_qty, existing_avg = self._positions[ticker]
            new_qty = existing_qty + quantity
            new_avg = (existing_qty * existing_avg + quantity * fill_price) / new_qty
            self._positions[ticker] = (new_qty, new_avg)
        else:
            self._positions[ticker] = (quantity, fill_price)

    def _apply_sell(self, ticker: str, quantity: Decimal) -> None:
        if ticker not in self._positions:
            raise ValueError(f"No position in '{ticker}' to sell")
        existing_qty, existing_avg = self._positions[ticker]
        if quantity > existing_qty:
            raise ValueError(
                f"Insufficient position in '{ticker}': "
                f"have {existing_qty}, trying to sell {quantity}"
            )
        new_qty = existing_qty - quantity
        self._positions[ticker] = (new_qty, existing_avg)
