from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from stocktrader.trading.mock_broker import MockBroker
from stocktrader.trading.models import Order, OrderSide, OrderType


def _make_order(ticker: str, side: OrderSide, quantity: Decimal) -> Order:
    return Order(
        order_id=uuid4(),
        ticker=ticker,
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
    )


def _broker(cash: Decimal = Decimal("10000"), slippage_bps: int = 5) -> MockBroker:
    broker = MockBroker(initial_cash=cash, slippage_bps=slippage_bps)
    return broker


# ---------------------------------------------------------------------------
# Buy order
# ---------------------------------------------------------------------------


async def test_buy_order_reduces_cash_and_creates_position() -> None:
    broker = _broker(cash=Decimal("10000"))
    broker.set_price("AAPL", Decimal("100"))

    order = _make_order("AAPL", OrderSide.BUY, Decimal("10"))
    fill = await broker.submit_order(order)

    # slippage: 100 * (1 + 5/10000) = 100.05 per share
    expected_price = Decimal("100") * (Decimal("1") + Decimal("5") / Decimal("10000"))
    expected_cost = expected_price * Decimal("10")

    assert fill.price == expected_price
    assert fill.quantity == Decimal("10")
    assert fill.side is OrderSide.BUY
    assert fill.order_id == order.order_id

    cash = await broker.get_cash()
    assert cash == Decimal("10000") - expected_cost

    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].ticker == "AAPL"
    assert positions[0].quantity == Decimal("10")
    assert positions[0].avg_cost == expected_price


async def test_buy_order_slippage_applied_correctly() -> None:
    broker = MockBroker(initial_cash=Decimal("100000"), slippage_bps=10)
    broker.set_price("TSLA", Decimal("200"))

    order = _make_order("TSLA", OrderSide.BUY, Decimal("5"))
    fill = await broker.submit_order(order)

    # 10 bps = 0.001 multiplier
    expected_price = Decimal("200") * (Decimal("1") + Decimal("10") / Decimal("10000"))
    assert fill.price == expected_price


# ---------------------------------------------------------------------------
# Sell order
# ---------------------------------------------------------------------------


async def test_sell_order_reduces_position_and_increases_cash() -> None:
    broker = _broker(cash=Decimal("10000"))
    broker.set_price("AAPL", Decimal("100"))

    buy_order = _make_order("AAPL", OrderSide.BUY, Decimal("10"))
    await broker.submit_order(buy_order)

    cash_after_buy = await broker.get_cash()

    sell_order = _make_order("AAPL", OrderSide.SELL, Decimal("5"))
    fill = await broker.submit_order(sell_order)

    # sell slippage: 100 * (1 - 5/10000)
    expected_sell_price = Decimal("100") * (
        Decimal("1") - Decimal("5") / Decimal("10000")
    )
    assert fill.price == expected_sell_price
    assert fill.side is OrderSide.SELL

    cash_after_sell = await broker.get_cash()
    assert cash_after_sell == cash_after_buy + expected_sell_price * Decimal("5")

    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == Decimal("5")


async def test_sell_order_slippage_applied_correctly() -> None:
    broker = MockBroker(initial_cash=Decimal("100000"), slippage_bps=20)
    broker.set_price("GOOG", Decimal("150"))

    buy_order = _make_order("GOOG", OrderSide.BUY, Decimal("10"))
    await broker.submit_order(buy_order)

    sell_order = _make_order("GOOG", OrderSide.SELL, Decimal("10"))
    fill = await broker.submit_order(sell_order)

    expected_price = Decimal("150") * (
        Decimal("1") - Decimal("20") / Decimal("10000")
    )
    assert fill.price == expected_price


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


async def test_insufficient_cash_raises_value_error() -> None:
    broker = MockBroker(initial_cash=Decimal("100"))
    broker.set_price("AAPL", Decimal("200"))

    order = _make_order("AAPL", OrderSide.BUY, Decimal("10"))  # costs ~2000
    with pytest.raises(ValueError, match="Insufficient cash"):
        await broker.submit_order(order)


async def test_insufficient_position_raises_value_error() -> None:
    broker = _broker(cash=Decimal("10000"))
    broker.set_price("AAPL", Decimal("100"))

    buy_order = _make_order("AAPL", OrderSide.BUY, Decimal("5"))
    await broker.submit_order(buy_order)

    sell_order = _make_order("AAPL", OrderSide.SELL, Decimal("10"))  # have only 5
    with pytest.raises(ValueError, match="Insufficient position"):
        await broker.submit_order(sell_order)


async def test_sell_with_no_position_raises_value_error() -> None:
    broker = _broker(cash=Decimal("10000"))
    broker.set_price("AAPL", Decimal("100"))

    sell_order = _make_order("AAPL", OrderSide.SELL, Decimal("1"))
    with pytest.raises(ValueError):
        await broker.submit_order(sell_order)


async def test_missing_price_raises_value_error() -> None:
    broker = _broker()
    order = _make_order("UNKNOWN", OrderSide.BUY, Decimal("1"))
    with pytest.raises(ValueError, match="No price available"):
        await broker.submit_order(order)


# ---------------------------------------------------------------------------
# Zero-quantity positions excluded
# ---------------------------------------------------------------------------


async def test_zero_quantity_position_excluded_from_get_positions() -> None:
    broker = _broker(cash=Decimal("10000"))
    broker.set_price("AAPL", Decimal("100"))

    buy_order = _make_order("AAPL", OrderSide.BUY, Decimal("3"))
    await broker.submit_order(buy_order)

    sell_order = _make_order("AAPL", OrderSide.SELL, Decimal("3"))
    await broker.submit_order(sell_order)

    positions = await broker.get_positions()
    assert positions == []


# ---------------------------------------------------------------------------
# Full round-trip
# ---------------------------------------------------------------------------


async def test_round_trip_buy_then_sell_reduces_cash_by_slippage() -> None:
    """Buy N shares then sell N shares; net cash loss equals 2x slippage."""
    initial_cash = Decimal("10000")
    price = Decimal("100")
    quantity = Decimal("10")
    slippage_bps = 5

    broker = MockBroker(initial_cash=initial_cash, slippage_bps=slippage_bps)
    broker.set_price("AAPL", price)

    buy_order = _make_order("AAPL", OrderSide.BUY, quantity)
    await broker.submit_order(buy_order)

    sell_order = _make_order("AAPL", OrderSide.SELL, quantity)
    await broker.submit_order(sell_order)

    final_cash = await broker.get_cash()

    # Each side applies 5 bps slippage against us.
    # Buy cost:  100 * 1.0005 * 10 = 1000.50
    # Sell recv: 100 * 0.9995 * 10 =  999.50
    # Net loss = 1.00
    slippage = Decimal(slippage_bps) / Decimal("10000")
    buy_price = price * (Decimal("1") + slippage)
    sell_price = price * (Decimal("1") - slippage)
    expected_cash = initial_cash - (buy_price - sell_price) * quantity

    assert final_cash == expected_cash

    positions = await broker.get_positions()
    assert positions == []


# ---------------------------------------------------------------------------
# Portfolio snapshot
# ---------------------------------------------------------------------------


async def test_get_portfolio_snapshot_is_consistent() -> None:
    broker = _broker(cash=Decimal("5000"))
    broker.set_price("MSFT", Decimal("50"))

    order = _make_order("MSFT", OrderSide.BUY, Decimal("20"))
    await broker.submit_order(order)

    snapshot = await broker.get_portfolio_snapshot()
    cash = await broker.get_cash()
    positions = await broker.get_positions()

    assert snapshot.cash == cash
    assert len(snapshot.positions) == len(positions)
    assert snapshot.positions[0].ticker == positions[0].ticker
    assert snapshot.positions[0].quantity == positions[0].quantity
    assert snapshot.positions[0].avg_cost == positions[0].avg_cost


async def test_price_oracle_used_when_price_map_empty() -> None:
    """price_oracle callable is consulted when set_price has not been called."""

    def oracle(ticker: str) -> Decimal:
        return Decimal("75")

    broker = MockBroker(
        initial_cash=Decimal("10000"), slippage_bps=0, price_oracle=oracle
    )

    order = _make_order("XYZ", OrderSide.BUY, Decimal("4"))
    fill = await broker.submit_order(order)
    assert fill.price == Decimal("75")


async def test_multiple_buys_compute_correct_avg_cost() -> None:
    broker = _broker(cash=Decimal("50000"))
    broker.set_price("AAPL", Decimal("100"))

    order1 = _make_order("AAPL", OrderSide.BUY, Decimal("10"))
    fill1 = await broker.submit_order(order1)

    broker.set_price("AAPL", Decimal("110"))
    order2 = _make_order("AAPL", OrderSide.BUY, Decimal("10"))
    fill2 = await broker.submit_order(order2)

    positions = await broker.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.quantity == Decimal("20")

    # avg_cost = (10 * fill1.price + 10 * fill2.price) / 20
    expected_avg = (fill1.price * Decimal("10") + fill2.price * Decimal("10")) / Decimal(
        "20"
    )
    assert pos.avg_cost == expected_avg
