from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from stocktrader.data.state_manager import StateManager
from stocktrader.trading.models import Fill, OrderSide

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fill(
    ticker: str,
    side: OrderSide,
    quantity: str,
    price: str,
    commission: str = "0",
) -> Fill:
    return Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        ticker=ticker,
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        commission=Decimal(commission),
    )


async def _fresh_manager(initial_cash: str = "100000") -> StateManager:
    sm = StateManager(
        db_url="sqlite+aiosqlite:///:memory:",
        initial_cash=Decimal(initial_cash),
    )
    await sm.init_db()
    return sm


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


async def test_init_db_creates_tables_and_sets_initial_cash() -> None:
    sm = await _fresh_manager("50000")
    snapshot = await sm._rebuild_portfolio_snapshot()
    assert snapshot.cash == Decimal("50000")
    assert snapshot.positions == []


async def test_init_db_idempotent() -> None:
    """Calling init_db twice does not reset cash."""
    sm = StateManager(
        db_url="sqlite+aiosqlite:///:memory:",
        initial_cash=Decimal("100000"),
    )
    await sm.init_db()
    # Simulate a BUY to change cash, then call init_db again
    fill = _make_fill("AAPL", OrderSide.BUY, "10", "100")
    await sm.record_fill(fill)
    cash_before = (await sm._rebuild_portfolio_snapshot()).cash
    await sm.init_db()  # must not reset cash
    cash_after = (await sm._rebuild_portfolio_snapshot()).cash
    assert cash_before == cash_after


# ---------------------------------------------------------------------------
# record_fill — BUY
# ---------------------------------------------------------------------------


async def test_buy_fill_reduces_cash_and_creates_position() -> None:
    sm = await _fresh_manager("10000")
    fill = _make_fill("AAPL", OrderSide.BUY, "10", "100")
    await sm.record_fill(fill)

    snapshot = await sm._rebuild_portfolio_snapshot()
    assert snapshot.cash == Decimal("10000") - Decimal("10") * Decimal("100")
    assert len(snapshot.positions) == 1
    pos = snapshot.positions[0]
    assert pos.ticker == "AAPL"
    assert pos.quantity == Decimal("10")
    assert pos.avg_cost == Decimal("100")


async def test_buy_fill_with_commission_reduces_cash_extra() -> None:
    sm = await _fresh_manager("10000")
    fill = _make_fill("AAPL", OrderSide.BUY, "10", "100", commission="5")
    await sm.record_fill(fill)

    snapshot = await sm._rebuild_portfolio_snapshot()
    # 10 * 100 + 5 commission = 1005
    assert snapshot.cash == Decimal("10000") - Decimal("1005")


async def test_two_buys_update_avg_cost_correctly() -> None:
    sm = await _fresh_manager("50000")
    fill1 = _make_fill("AAPL", OrderSide.BUY, "10", "100")
    fill2 = _make_fill("AAPL", OrderSide.BUY, "10", "110")
    await sm.record_fill(fill1)
    await sm.record_fill(fill2)

    snapshot = await sm._rebuild_portfolio_snapshot()
    assert len(snapshot.positions) == 1
    pos = snapshot.positions[0]
    assert pos.quantity == Decimal("20")
    # avg_cost = (10*100 + 10*110) / 20 = 105
    assert pos.avg_cost == Decimal("105")


# ---------------------------------------------------------------------------
# record_fill — SELL
# ---------------------------------------------------------------------------


async def test_sell_fill_increases_cash_and_reduces_position() -> None:
    sm = await _fresh_manager("10000")
    buy = _make_fill("AAPL", OrderSide.BUY, "10", "100")
    await sm.record_fill(buy)
    cash_after_buy = (await sm._rebuild_portfolio_snapshot()).cash

    sell = _make_fill("AAPL", OrderSide.SELL, "5", "105")
    await sm.record_fill(sell)

    snapshot = await sm._rebuild_portfolio_snapshot()
    assert snapshot.cash == cash_after_buy + Decimal("5") * Decimal("105")
    assert len(snapshot.positions) == 1
    assert snapshot.positions[0].quantity == Decimal("5")


async def test_full_sell_removes_position_row() -> None:
    sm = await _fresh_manager("10000")
    buy = _make_fill("AAPL", OrderSide.BUY, "10", "100")
    await sm.record_fill(buy)

    sell = _make_fill("AAPL", OrderSide.SELL, "10", "110")
    await sm.record_fill(sell)

    snapshot = await sm._rebuild_portfolio_snapshot()
    assert snapshot.positions == []


async def test_sell_with_commission_reduces_proceeds() -> None:
    sm = await _fresh_manager("10000")
    buy = _make_fill("AAPL", OrderSide.BUY, "10", "100")
    await sm.record_fill(buy)
    cash_after_buy = (await sm._rebuild_portfolio_snapshot()).cash

    sell = _make_fill("AAPL", OrderSide.SELL, "5", "105", commission="3")
    await sm.record_fill(sell)

    snapshot = await sm._rebuild_portfolio_snapshot()
    # proceeds = 5*105 - 3 = 522
    assert snapshot.cash == cash_after_buy + Decimal("522")


# ---------------------------------------------------------------------------
# get_fills
# ---------------------------------------------------------------------------


async def test_get_fills_returns_fills_descending() -> None:
    sm = await _fresh_manager()
    base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    fill1 = Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=Decimal("5"),
        price=Decimal("100"),
        filled_at=base_time,
    )
    fill2 = Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        ticker="MSFT",
        side=OrderSide.BUY,
        quantity=Decimal("3"),
        price=Decimal("200"),
        filled_at=base_time + timedelta(seconds=1),
    )
    await sm.record_fill(fill1)
    await sm.record_fill(fill2)

    fills = await sm.get_fills()
    # Most recent fill first
    assert len(fills) == 2
    # MSFT was recorded after AAPL so it should come first
    assert fills[0].ticker == "MSFT"
    assert fills[1].ticker == "AAPL"


async def test_get_fills_respects_limit() -> None:
    sm = await _fresh_manager("1000000")
    for _i in range(5):
        fill = _make_fill("AAPL", OrderSide.BUY, "1", "100")
        await sm.record_fill(fill)

    fills = await sm.get_fills(limit=3)
    assert len(fills) == 3


async def test_get_fills_empty_when_no_fills() -> None:
    sm = await _fresh_manager()
    fills = await sm.get_fills()
    assert fills == []


# ---------------------------------------------------------------------------
# Multiple sequential fills maintain consistent state
# ---------------------------------------------------------------------------


async def test_multiple_sequential_fills_consistent_state() -> None:
    sm = await _fresh_manager("100000")

    # Buy AAPL and MSFT
    await sm.record_fill(_make_fill("AAPL", OrderSide.BUY, "10", "100"))
    await sm.record_fill(_make_fill("MSFT", OrderSide.BUY, "5", "200"))
    # Sell some AAPL
    await sm.record_fill(_make_fill("AAPL", OrderSide.SELL, "5", "110"))

    snapshot = await sm._rebuild_portfolio_snapshot()

    # Cash: 100000 - 1000 - 1000 + 550 = 98550
    assert snapshot.cash == Decimal("98550")

    tickers = {p.ticker: p for p in snapshot.positions}
    assert "AAPL" in tickers
    assert "MSFT" in tickers
    assert tickers["AAPL"].quantity == Decimal("5")
    assert tickers["MSFT"].quantity == Decimal("5")

    fills = await sm.get_fills()
    assert len(fills) == 3
