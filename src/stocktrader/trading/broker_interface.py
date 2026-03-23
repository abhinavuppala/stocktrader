from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from stocktrader.trading.models import Fill, Order, PortfolioSnapshot, Position


class IBroker(ABC):
    @abstractmethod
    async def submit_order(self, order: Order) -> Fill: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_cash(self) -> Decimal: ...

    @abstractmethod
    async def get_portfolio_snapshot(self) -> PortfolioSnapshot: ...
