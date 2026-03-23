from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


class Order(BaseModel):
    order_id: UUID
    ticker: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Fill(BaseModel):
    fill_id: UUID
    order_id: UUID
    ticker: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    filled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    commission: Decimal = Decimal("0")


class Position(BaseModel):
    ticker: str
    quantity: Decimal
    avg_cost: Decimal


class PortfolioSnapshot(BaseModel):
    positions: list[Position]
    cash: Decimal
    snapshot_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RebalanceDecision(BaseModel):
    targets: dict[str, float]  # ticker → target weight, 0.0–1.0
    rationale: str
    cycle_id: UUID

    @model_validator(mode="after")
    def _weights_sum_at_most_one(self) -> RebalanceDecision:
        total = sum(self.targets.values())
        if total > 1.0 + 1e-9:
            raise ValueError(
                f"Target weights sum to {total:.6f}, which exceeds 1.0"
            )
        return self
