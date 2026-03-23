from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

# ---------------------------------------------------------------------------
# SQLAlchemy table definitions (Core style)
# ---------------------------------------------------------------------------
from sqlalchemy import Column, MetaData, String, Table, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stocktrader.trading.models import Fill, OrderSide, PortfolioSnapshot, Position

metadata = MetaData()

portfolio_state_table = Table(
    "portfolio_state",
    metadata,
    Column("id", String, primary_key=True),  # always "1"
    Column("cash", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

positions_table = Table(
    "positions",
    metadata,
    Column("ticker", String, primary_key=True),
    Column("quantity", String, nullable=False),
    Column("avg_cost", String, nullable=False),
)

fills_table = Table(
    "fills",
    metadata,
    Column("fill_id", String, primary_key=True),
    Column("order_id", String, nullable=False),
    Column("ticker", String, nullable=False),
    Column("side", String, nullable=False),
    Column("quantity", String, nullable=False),
    Column("price", String, nullable=False),
    Column("commission", String, nullable=False),
    Column("filled_at", String, nullable=False),
)


class StateManager:
    """Async SQLite persistence via SQLAlchemy 2.0 + aiosqlite."""

    def __init__(
        self,
        db_url: str = "sqlite+aiosqlite:///stocktrader.db",
        initial_cash: Decimal = Decimal("100000.00"),
    ) -> None:
        self._engine = create_async_engine(db_url, echo=False)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )
        self._initial_cash = initial_cash

    async def init_db(self) -> None:
        """Create tables if they do not exist; seed portfolio_state if empty."""
        async with self._engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

        # Insert the single portfolio_state row if it doesn't exist yet.
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(portfolio_state_table).where(
                        portfolio_state_table.c.id == "1"
                    )
                )
                row = result.fetchone()
                if row is None:
                    await session.execute(
                        portfolio_state_table.insert().values(
                            id="1",
                            cash=str(self._initial_cash),
                            updated_at=datetime.now(UTC).isoformat(),
                        )
                    )

    async def record_fill(self, fill: Fill) -> None:
        """Persist a fill and atomically update cash + position."""
        async with self._session_factory() as session:
            async with session.begin():
                # 1. Insert fill row
                await session.execute(
                    fills_table.insert().values(
                        fill_id=str(fill.fill_id),
                        order_id=str(fill.order_id),
                        ticker=fill.ticker,
                        side=fill.side.value,
                        quantity=str(fill.quantity),
                        price=str(fill.price),
                        commission=str(fill.commission),
                        filled_at=fill.filled_at.isoformat(),
                    )
                )

                # 2. Fetch current cash
                state_result = await session.execute(
                    select(portfolio_state_table).where(
                        portfolio_state_table.c.id == "1"
                    )
                )
                state_row = state_result.fetchone()
                current_cash = Decimal(state_row[1]) if state_row else self._initial_cash

                trade_value = fill.quantity * fill.price

                if fill.side is OrderSide.BUY:
                    new_cash = current_cash - trade_value - fill.commission
                else:
                    new_cash = current_cash + trade_value - fill.commission

                # 3. Update cash
                await session.execute(
                    portfolio_state_table.update()
                    .where(portfolio_state_table.c.id == "1")
                    .values(
                        cash=str(new_cash),
                        updated_at=datetime.now(UTC).isoformat(),
                    )
                )

                # 4. Upsert position
                pos_result = await session.execute(
                    select(positions_table).where(
                        positions_table.c.ticker == fill.ticker
                    )
                )
                pos_row = pos_result.fetchone()

                if fill.side is OrderSide.BUY:
                    if pos_row is None:
                        # New position
                        await session.execute(
                            positions_table.insert().values(
                                ticker=fill.ticker,
                                quantity=str(fill.quantity),
                                avg_cost=str(fill.price),
                            )
                        )
                    else:
                        existing_qty = Decimal(pos_row[1])
                        existing_avg = Decimal(pos_row[2])
                        new_qty = existing_qty + fill.quantity
                        new_avg = (
                            existing_qty * existing_avg + fill.quantity * fill.price
                        ) / new_qty
                        await session.execute(
                            positions_table.update()
                            .where(positions_table.c.ticker == fill.ticker)
                            .values(quantity=str(new_qty), avg_cost=str(new_avg))
                        )
                else:  # SELL
                    if pos_row is None:
                        # No position to sell from — this should not happen in
                        # normal usage but we handle it gracefully.
                        return
                    existing_qty = Decimal(pos_row[1])
                    new_qty = existing_qty - fill.quantity
                    if new_qty <= Decimal("0"):
                        # Remove the row entirely
                        await session.execute(
                            delete(positions_table).where(
                                positions_table.c.ticker == fill.ticker
                            )
                        )
                    else:
                        await session.execute(
                            positions_table.update()
                            .where(positions_table.c.ticker == fill.ticker)
                            .values(quantity=str(new_qty))
                        )

    async def get_fills(self, limit: int = 100) -> list[Fill]:
        """Return recent fills ordered by filled_at descending."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(fills_table)
                .order_by(fills_table.c.filled_at.desc())
                .limit(limit)
            )
            rows = result.fetchall()

        return [
            Fill(
                fill_id=UUID(row[0]),
                order_id=UUID(row[1]),
                ticker=row[2],
                side=OrderSide(row[3]),
                quantity=Decimal(row[4]),
                price=Decimal(row[5]),
                commission=Decimal(row[6]),
                filled_at=datetime.fromisoformat(row[7]),
            )
            for row in rows
        ]

    async def _rebuild_portfolio_snapshot(self) -> PortfolioSnapshot:
        """Rebuild a PortfolioSnapshot directly from the database state."""
        async with self._session_factory() as session:
            state_result = await session.execute(
                select(portfolio_state_table).where(
                    portfolio_state_table.c.id == "1"
                )
            )
            state_row = state_result.fetchone()
            cash = Decimal(state_row[1]) if state_row else self._initial_cash

            pos_result = await session.execute(select(positions_table))
            pos_rows = pos_result.fetchall()

        positions = [
            Position(
                ticker=row[0],
                quantity=Decimal(row[1]),
                avg_cost=Decimal(row[2]),
            )
            for row in pos_rows
        ]
        return PortfolioSnapshot(positions=positions, cash=cash)
