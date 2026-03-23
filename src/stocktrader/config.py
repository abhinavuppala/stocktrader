from __future__ import annotations

from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        yaml_file="config.yaml",
        extra="ignore",
    )

    # Broker
    broker_mode: str = "mock"  # "mock" | "alpaca"
    initial_cash: Decimal = Decimal("100000.00")

    # Risk limits
    max_position_pct: float = Field(default=0.40)
    max_delta_pct: float = Field(default=0.20)
    min_cash_pct: float = Field(default=0.10)
    max_daily_trades: int = Field(default=10)

    # Simulation
    slippage_bps: int = Field(default=5)
    min_trade_value: Decimal = Decimal("1.00")

    # Logging
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
