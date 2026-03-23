from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from stocktrader.trading.models import (
    Order,
    OrderSide,
    PortfolioSnapshot,
    Position,
    RebalanceDecision,
)
from stocktrader.trading.position_manager import PositionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(
    positions: list[tuple[str, Decimal, Decimal]] | None = None,
    cash: Decimal = Decimal("10000"),
) -> PortfolioSnapshot:
    """Build a PortfolioSnapshot from (ticker, quantity, avg_cost) tuples."""
    pos_list: list[Position] = []
    if positions:
        for ticker, qty, avg_cost in positions:
            pos_list.append(Position(ticker=ticker, quantity=qty, avg_cost=avg_cost))
    return PortfolioSnapshot(positions=pos_list, cash=cash)


def _decision(
    targets: dict[str, float],
    rationale: str = "test",
) -> RebalanceDecision:
    return RebalanceDecision(targets=targets, rationale=rationale, cycle_id=uuid4())


def _orders_by_ticker(orders: list[Order]) -> dict[str, Order]:
    return {o.ticker: o for o in orders}


# ---------------------------------------------------------------------------
# RebalanceDecision validation
# ---------------------------------------------------------------------------


def test_weights_summing_over_one_raises_value_error() -> None:
    with pytest.raises(ValueError, match="exceeds 1.0"):
        _decision({"AAPL": 0.7, "TSLA": 0.4})  # sum = 1.1


def test_weights_summing_to_exactly_one_is_valid() -> None:
    dec = _decision({"AAPL": 0.6, "TSLA": 0.4})
    assert abs(sum(dec.targets.values()) - 1.0) < 1e-9


def test_weights_summing_to_less_than_one_is_valid() -> None:
    dec = _decision({"AAPL": 0.5})
    assert dec.targets["AAPL"] == 0.5


# ---------------------------------------------------------------------------
# Basic rebalance
# ---------------------------------------------------------------------------


def test_basic_rebalance_produces_correct_buy_and_sell() -> None:
    """Portfolio: $10 000 cash + 10 AAPL @ $100, 20 TSLA @ $50.
    Targets: AAPL 60%, TSLA 20%.

    Total value = 10000 + 10*100 + 20*50 = 10000 + 1000 + 1000 = 12000
    AAPL target $7200, current $1000 → BUY ~$6200 worth  → 62 shares
    TSLA target $2400, current $1000 → BUY ~$1400 worth  → 28 shares
    """
    pm = PositionManager()
    portfolio = _snapshot(
        positions=[
            ("AAPL", Decimal("10"), Decimal("100")),
            ("TSLA", Decimal("20"), Decimal("50")),
        ],
        cash=Decimal("10000"),
    )
    prices = {"AAPL": Decimal("100"), "TSLA": Decimal("50")}
    dec = _decision({"AAPL": 0.6, "TSLA": 0.2})

    orders = pm.generate_orders(dec, portfolio, prices)
    by_ticker = _orders_by_ticker(orders)

    assert "AAPL" in by_ticker
    assert by_ticker["AAPL"].side == OrderSide.BUY
    # delta = 7200 - 1000 = 6200 / 100 = 62
    assert by_ticker["AAPL"].quantity == Decimal("62.000000")

    assert "TSLA" in by_ticker
    assert by_ticker["TSLA"].side == OrderSide.BUY
    # delta = 2400 - 1000 = 1400 / 50 = 28
    assert by_ticker["TSLA"].quantity == Decimal("28.000000")


def test_rebalance_produces_sell_when_overweight() -> None:
    """Portfolio: $0 cash, 100 AAPL @ $100.
    Target: AAPL 50%.

    Total value = 10 000
    AAPL target $5 000, current $10 000 → SELL 50 shares.
    """
    pm = PositionManager()
    portfolio = _snapshot(
        positions=[("AAPL", Decimal("100"), Decimal("100"))],
        cash=Decimal("0"),
    )
    prices = {"AAPL": Decimal("100")}
    dec = _decision({"AAPL": 0.5})

    orders = pm.generate_orders(dec, portfolio, prices)
    by_ticker = _orders_by_ticker(orders)

    assert "AAPL" in by_ticker
    assert by_ticker["AAPL"].side == OrderSide.SELL
    assert by_ticker["AAPL"].quantity == Decimal("50.000000")


# ---------------------------------------------------------------------------
# Noise-trade suppression
# ---------------------------------------------------------------------------


def test_noise_trade_below_min_value_is_skipped() -> None:
    """delta of $0.50 with min_trade_value=$1.00 should produce no order."""
    pm = PositionManager(min_trade_value=Decimal("1.00"))
    # Total value = $1000 cash only
    # AAPL target 10% = $100; current = $99.50 → delta $0.50 — skip
    portfolio = _snapshot(
        positions=[("AAPL", Decimal("0.995"), Decimal("100"))],
        cash=Decimal("900.5"),
    )
    prices = {"AAPL": Decimal("100")}
    dec = _decision({"AAPL": 0.1})

    orders = pm.generate_orders(dec, portfolio, prices)
    assert orders == []


def test_trade_at_min_value_boundary_is_included() -> None:
    """delta of exactly $1.00 should produce an order."""
    pm = PositionManager(min_trade_value=Decimal("1.00"))
    # Total = $1000; AAPL target 10.1% = $101; current = $100 → delta $1.00
    portfolio = _snapshot(
        positions=[("AAPL", Decimal("1"), Decimal("100"))],
        cash=Decimal("900"),
    )
    prices = {"AAPL": Decimal("100")}
    dec = _decision({"AAPL": 0.101})

    orders = pm.generate_orders(dec, portfolio, prices)
    assert len(orders) == 1
    assert orders[0].ticker == "AAPL"


# ---------------------------------------------------------------------------
# Full sell for tickers not in target weights
# ---------------------------------------------------------------------------


def test_ticker_not_in_targets_gets_full_sell() -> None:
    """MSFT is held but absent from target weights — expect a full SELL order."""
    pm = PositionManager()
    portfolio = _snapshot(
        positions=[("MSFT", Decimal("10"), Decimal("50"))],
        cash=Decimal("500"),
    )
    prices = {"MSFT": Decimal("50")}
    dec = _decision({})  # no targets at all

    orders = pm.generate_orders(dec, portfolio, prices)
    by_ticker = _orders_by_ticker(orders)

    assert "MSFT" in by_ticker
    assert by_ticker["MSFT"].side == OrderSide.SELL
    # delta = 0 - 500 = -500 / 50 = 10 shares
    assert by_ticker["MSFT"].quantity == Decimal("10.000000")


# ---------------------------------------------------------------------------
# CASH key in targets is silently ignored
# ---------------------------------------------------------------------------


def test_cash_key_in_targets_is_ignored() -> None:
    pm = PositionManager()
    portfolio = _snapshot(cash=Decimal("10000"))
    prices: dict[str, Decimal] = {}
    dec = _decision({"CASH": 0.3})

    orders = pm.generate_orders(dec, portfolio, prices)
    assert orders == []


def test_cash_key_case_insensitive_ignored() -> None:
    pm = PositionManager()
    portfolio = _snapshot(cash=Decimal("10000"))
    prices: dict[str, Decimal] = {}
    dec = _decision({"CASH": 1.0})  # weights sum to 1.0, all cash

    orders = pm.generate_orders(dec, portfolio, prices)
    assert orders == []


# ---------------------------------------------------------------------------
# Empty portfolio + target weights → all BUY orders
# ---------------------------------------------------------------------------


def test_empty_portfolio_produces_all_buys() -> None:
    """No positions, only cash. All targets should produce BUY orders."""
    pm = PositionManager()
    portfolio = _snapshot(cash=Decimal("10000"))
    prices = {"AAPL": Decimal("100"), "GOOG": Decimal("200")}
    dec = _decision({"AAPL": 0.4, "GOOG": 0.4})

    orders = pm.generate_orders(dec, portfolio, prices)
    by_ticker = _orders_by_ticker(orders)

    assert len(orders) == 2
    assert by_ticker["AAPL"].side == OrderSide.BUY
    assert by_ticker["AAPL"].quantity == Decimal("40.000000")  # 4000/100
    assert by_ticker["GOOG"].side == OrderSide.BUY
    assert by_ticker["GOOG"].quantity == Decimal("20.000000")  # 4000/200


# ---------------------------------------------------------------------------
# All-cash portfolio (no positions)
# ---------------------------------------------------------------------------


def test_all_cash_portfolio_buys_correct_amounts() -> None:
    """$5000 cash, target 100% TSLA at $250/share → BUY 20 shares."""
    pm = PositionManager()
    portfolio = _snapshot(cash=Decimal("5000"))
    prices = {"TSLA": Decimal("250")}
    dec = _decision({"TSLA": 1.0})

    orders = pm.generate_orders(dec, portfolio, prices)
    assert len(orders) == 1
    assert orders[0].ticker == "TSLA"
    assert orders[0].side == OrderSide.BUY
    assert orders[0].quantity == Decimal("20.000000")


# ---------------------------------------------------------------------------
# Sanity: total order value doesn't exceed portfolio value
# ---------------------------------------------------------------------------


def test_total_buy_order_value_does_not_exceed_portfolio_value() -> None:
    """The sum of BUY order notional values must not exceed total portfolio value."""
    pm = PositionManager()
    portfolio = _snapshot(
        positions=[
            ("AAPL", Decimal("5"), Decimal("100")),
            ("TSLA", Decimal("10"), Decimal("50")),
        ],
        cash=Decimal("5000"),
    )
    prices = {"AAPL": Decimal("100"), "TSLA": Decimal("50")}
    # total value = 5000 + 500 + 500 = 6000
    dec = _decision({"AAPL": 0.5, "TSLA": 0.3})

    orders = pm.generate_orders(dec, portfolio, prices)

    total_value = portfolio.cash + sum(
        p.quantity * prices[p.ticker] for p in portfolio.positions
    )
    buy_notional = sum(
        o.quantity * prices[o.ticker] for o in orders if o.side == OrderSide.BUY
    )
    assert buy_notional <= total_value


# ---------------------------------------------------------------------------
# ValueError when current position has no price
# ---------------------------------------------------------------------------


def test_missing_price_for_held_ticker_raises_value_error() -> None:
    pm = PositionManager()
    portfolio = _snapshot(
        positions=[("AAPL", Decimal("10"), Decimal("100"))],
        cash=Decimal("0"),
    )
    # AAPL held but not in prices map
    prices: dict[str, Decimal] = {}
    dec = _decision({})

    with pytest.raises(ValueError, match="AAPL"):
        pm.generate_orders(dec, portfolio, prices)


# ---------------------------------------------------------------------------
# Fractional share quantities are rounded to 6 decimal places
# ---------------------------------------------------------------------------


def test_fractional_share_quantity_rounded_to_six_places() -> None:
    """price=$3, delta=$10 → 3.333... shares → truncated to 3.333333."""
    pm = PositionManager()
    portfolio = _snapshot(cash=Decimal("10"))
    prices = {"XYZ": Decimal("3")}
    dec = _decision({"XYZ": 1.0})

    orders = pm.generate_orders(dec, portfolio, prices)
    assert len(orders) == 1
    # 10 / 3 = 3.3333... → floor to 6 dp = 3.333333
    assert orders[0].quantity == Decimal("3.333333")
