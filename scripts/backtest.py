#!/usr/bin/env python
"""
Run a historical simulation over N days.

Usage:
    python scripts/backtest.py --tickers AAPL,MSFT,GOOGL --days 30
"""
from __future__ import annotations

import argparse
import asyncio
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from stocktrader.agent.trading_agent import MomentumAgent
from stocktrader.data.models import MarketSnapshot
from stocktrader.data.state_manager import StateManager
from stocktrader.trading.mock_broker import MockBroker
from stocktrader.trading.position_manager import PositionManager
from stocktrader.trading.risk_guard import RiskGuard, RiskViolationError


def generate_prices(
    tickers: list[str], days: int
) -> list[dict[str, Decimal]]:
    """Generate synthetic price series for each ticker using a random walk."""
    # Initial prices: random between 50 and 200
    current: dict[str, Decimal] = {
        t: Decimal(str(round(random.uniform(50.0, 200.0), 2))) for t in tickers
    }

    history: list[dict[str, Decimal]] = []
    for _ in range(days):
        for ticker in tickers:
            change_pct = random.uniform(-0.02, 0.02)
            new_price = current[ticker] * Decimal(str(1.0 + change_pct))
            # Round to 2 decimal places, ensure positive
            current[ticker] = max(Decimal("0.01"), new_price.quantize(Decimal("0.01")))
        history.append(dict(current))

    return history


async def main() -> None:
    parser = argparse.ArgumentParser(description="StockTrader backtest simulation")
    parser.add_argument(
        "--tickers",
        type=str,
        default="AAPL,MSFT,GOOGL",
        help="Comma-separated list of ticker symbols",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of trading days to simulate",
    )
    args = parser.parse_args()

    tickers: list[str] = [t.strip().upper() for t in args.tickers.split(",")]
    days: int = args.days

    print(f"Starting backtest: {tickers}, {days} days")
    print("-" * 60)

    # --- Setup ---
    initial_cash = Decimal("100000")
    state_manager = StateManager(
        db_url="sqlite+aiosqlite:///:memory:",
        initial_cash=initial_cash,
    )
    await state_manager.init_db()

    top_n = min(3, len(tickers))
    agent = MomentumAgent(universe=tickers, top_n=top_n, max_position_pct=0.30)
    position_manager = PositionManager()
    risk_guard = RiskGuard()
    broker = MockBroker(initial_cash=initial_cash)

    # Generate synthetic price data
    price_history = generate_prices(tickers, days)

    start_date = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    # --- Simulation loop ---
    for day_idx, prices in enumerate(price_history):
        today = start_date + timedelta(days=day_idx)

        # Update broker prices
        for ticker, price in prices.items():
            broker.set_price(ticker, price)

        # Build market snapshot
        market = MarketSnapshot(prices=prices, snapshot_at=today)

        # Build portfolio snapshot from broker
        portfolio = await broker.get_portfolio_snapshot()

        # Random momentum scores for this day
        scores = {t: random.random() for t in tickers}

        # Agent decision
        decision = await agent.decide(portfolio, market, scores=scores)

        # Generate orders
        orders = position_manager.generate_orders(decision, portfolio, prices)

        # Risk check
        try:
            risk_guard.validate(decision, portfolio, prices)
        except RiskViolationError as exc:
            print(f"Day {day_idx + 1:3d} | RISK VIOLATION: {exc} — skipping")
            continue

        # Submit orders and record fills
        for order in orders:
            try:
                fill = await broker.submit_order(order)
                await state_manager.record_fill(fill)
            except ValueError as exc:
                print(f"Day {day_idx + 1:3d} | Order error ({order.ticker}): {exc}")

        # Summary for the day
        snapshot = await broker.get_portfolio_snapshot()
        position_values = {
            p.ticker: p.quantity * prices[p.ticker]
            for p in snapshot.positions
            if p.ticker in prices
        }
        portfolio_value = snapshot.cash + sum(position_values.values())

        pos_summary = (
            {p.ticker: int(p.quantity) for p in snapshot.positions}
            if snapshot.positions
            else {}
        )

        print(
            f"Day {day_idx + 1:3d} | "
            f"Cash: ${float(snapshot.cash):,.2f} | "
            f"Positions: {pos_summary} | "
            f"Portfolio Value: ${float(portfolio_value):,.2f}"
        )

    # --- Final summary ---
    final_snapshot = await broker.get_portfolio_snapshot()
    final_prices = price_history[-1] if price_history else {}
    final_position_value = sum(
        p.quantity * final_prices.get(p.ticker, Decimal("0"))
        for p in final_snapshot.positions
    )
    final_value = final_snapshot.cash + final_position_value

    total_return_pct = float((final_value - initial_cash) / initial_cash * 100)

    print("-" * 60)
    print(f"Starting value: ${float(initial_cash):,.2f}")
    print(f"Ending value:   ${float(final_value):,.2f}")
    print(f"Total return:   {total_return_pct:+.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
