from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class NewsArticle(BaseModel):
    article_id: UUID
    ticker: str
    headline: str
    source: str
    published_at: datetime  # UTC-aware
    url: str
    sentiment_score: float | None = None  # filled by SentimentAnalyzer later


class PriceBar(BaseModel):
    ticker: str
    timestamp: datetime  # UTC-aware
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class MarketSnapshot(BaseModel):
    prices: dict[str, Decimal]  # ticker → latest close price
    snapshot_at: datetime
