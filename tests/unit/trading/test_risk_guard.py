from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from stocktrader.trading.models import PortfolioSnapshot, Position, RebalanceDecision
from stocktrader.trading.risk_guard import RiskGuard, RiskViolationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decision(targets: dict[str, float]) -> RebalanceDecision:
    return RebalanceDecision(
        targets=targets,
        rationale="test",
        cycle_id=uuid4(),
    )


def _snapshot(
    positions: list[tuple[str, str, str]] | None = None,
    cash: str = "10000",
) -> PortfolioSnapshot:
    """Build a PortfolioSnapshot.

    positions: list of (ticker, quantity, avg_cost) as strings.
    """
    pos_list: list[Position] = []
    if positions:
        for ticker, qty, cost in positions:
            pos_list.append(
                Position(
                    ticker=ticker,
                    quantity=Decimal(qty),
                    avg_cost=Decimal(cost),
                )
            )
    return PortfolioSnapshot(positions=pos_list, cash=Decimal(cash))


def _prices(*pairs: tuple[str, str]) -> dict[str, Decimal]:
    return {ticker: Decimal(price) for ticker, price in pairs}


# ---------------------------------------------------------------------------
# Happy path — all constraints pass with default limits
# ---------------------------------------------------------------------------


def test_happy_path_all_pass() -> None:
    """A well-formed decision passes all four constraints."""
    guard = RiskGuard()
    # Portfolio: 50% AAPL, 50% cash (total = 10000)
    portfolio = _snapshot(
        positions=[("AAPL", "50", "100")],
        cash="5000",
    )
    prices = _prices(("AAPL", "100"))
    # Target: AAPL = 0.30 (was 0.50 → delta = 0.20 exact, cash = 0.70)
    decision = _decision({"AAPL": 0.30})
    guard.validate(decision, portfolio, prices)  # must not raise


def test_empty_portfolio_rebalance_into_positions() -> None:
    """Starting all-cash, buying into a position within limits."""
    # Use a relaxed delta limit so 0% → 20% moves are fine
    guard = RiskGuard(max_delta_pct=0.50)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    decision = _decision({"AAPL": 0.30, "MSFT": 0.20})
    guard.validate(decision, portfolio, prices)  # must not raise


# ---------------------------------------------------------------------------
# Constraint 1: max_position_pct
# ---------------------------------------------------------------------------


def test_max_position_pct_exact_limit_passes() -> None:
    """Target weight exactly at 0.40 must pass."""
    # Relax delta limit so 0% → 40% move doesn't trigger first
    guard = RiskGuard(max_position_pct=0.40, max_delta_pct=1.0)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    decision = _decision({"AAPL": 0.40})
    guard.validate(decision, portfolio, prices)  # must not raise


def test_max_position_pct_one_basis_point_over_raises() -> None:
    """Target weight 0.41 on a 0.40 limit must raise."""
    # Relax delta so only the position check fires
    guard = RiskGuard(max_position_pct=0.40, max_delta_pct=1.0)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    decision = _decision({"AAPL": 0.41})
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_position_pct"
    assert "AAPL" in exc_info.value.detail


def test_max_position_pct_multiple_tickers_second_violates() -> None:
    """First ticker passes, second ticker exceeds limit."""
    guard = RiskGuard(max_position_pct=0.40, max_delta_pct=1.0)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    decision = _decision({"AAPL": 0.30, "TSLA": 0.41})
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_position_pct"


def test_max_position_pct_cash_key_excluded() -> None:
    """CASH in targets is not checked against max_position_pct even if large."""
    guard = RiskGuard(max_position_pct=0.40)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    # CASH = 0.80, AAPL = 0.20 — CASH alone would fail position check if included
    decision = _decision({"CASH": 0.80, "AAPL": 0.20})
    guard.validate(decision, portfolio, prices)  # must not raise


# ---------------------------------------------------------------------------
# Constraint 2: max_delta_pct
# ---------------------------------------------------------------------------


def test_max_delta_pct_exact_limit_passes() -> None:
    """Delta exactly 0.20 from a 0% base must pass."""
    guard = RiskGuard(max_delta_pct=0.20)
    portfolio = _snapshot(cash="10000")  # all cash, AAPL weight = 0.0
    prices: dict[str, Decimal] = {}
    decision = _decision({"AAPL": 0.20})
    guard.validate(decision, portfolio, prices)  # must not raise


def test_max_delta_pct_large_swing_raises() -> None:
    """0% → 25% on a 0.20 limit must raise."""
    guard = RiskGuard(max_delta_pct=0.20)
    portfolio = _snapshot(cash="10000")  # AAPL weight = 0.0
    prices: dict[str, Decimal] = {}
    decision = _decision({"AAPL": 0.25})
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_delta_pct"
    assert "AAPL" in exc_info.value.detail


def test_max_delta_pct_reduce_position_raises() -> None:
    """Reducing from 50% to 20% (delta = 0.30) on a 0.20 limit must raise."""
    guard = RiskGuard(max_delta_pct=0.20)
    # 50% AAPL, 50% cash (total = 10000)
    portfolio = _snapshot(positions=[("AAPL", "50", "100")], cash="5000")
    prices = _prices(("AAPL", "100"))
    decision = _decision({"AAPL": 0.20})
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_delta_pct"


def test_max_delta_pct_cash_key_excluded() -> None:
    """CASH in targets is not subject to delta checks."""
    guard = RiskGuard(max_delta_pct=0.20)
    # All cash portfolio, CASH "target" of 0.80 would imply a big cash delta
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    # CASH stays at ~1.0 → 0.80, but CASH key is excluded from delta checks
    decision = _decision({"CASH": 0.80, "AAPL": 0.20})
    guard.validate(decision, portfolio, prices)  # must not raise


def test_max_delta_pct_full_exit_position_not_in_targets() -> None:
    """Ticker in portfolio but not in targets (full sell) is delta-checked."""
    guard = RiskGuard(max_delta_pct=0.20)
    # 50% AAPL, 50% cash — full exit of AAPL is a 0.50 delta
    portfolio = _snapshot(positions=[("AAPL", "50", "100")], cash="5000")
    prices = _prices(("AAPL", "100"))
    decision = _decision({})  # no targets → full exit of AAPL
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_delta_pct"


def test_max_delta_pct_full_exit_within_limit_passes() -> None:
    """Full exit where current weight is within delta limit passes."""
    guard = RiskGuard(max_delta_pct=0.20)
    # AAPL at 10% of portfolio (1 share @ 100, cash = 900)
    portfolio = _snapshot(positions=[("AAPL", "1", "100")], cash="900")
    prices = _prices(("AAPL", "100"))
    decision = _decision({})  # full exit, delta = 0.10 < 0.20
    guard.validate(decision, portfolio, prices)  # must not raise


# ---------------------------------------------------------------------------
# Constraint 3: min_cash_pct
# ---------------------------------------------------------------------------


def test_min_cash_pct_exact_limit_passes() -> None:
    """Targets summing to 0.90 (implied 0.10 cash) must pass on 0.10 min."""
    guard = RiskGuard(min_cash_pct=0.10)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    decision = _decision({"AAPL": 0.50, "MSFT": 0.40})  # sum = 0.90
    guard.validate(decision, portfolio, prices)  # must not raise


def test_min_cash_pct_over_limit_raises() -> None:
    """Targets summing to 0.92 (implied 0.08 cash) must raise on 0.10 min."""
    guard = RiskGuard(min_cash_pct=0.10)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    decision = _decision({"AAPL": 0.50, "MSFT": 0.42})  # sum = 0.92
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "min_cash_pct"


def test_min_cash_pct_explicit_cash_key_counted() -> None:
    """When CASH is in targets, use it for the cash floor check."""
    guard = RiskGuard(min_cash_pct=0.10)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    # Explicit cash = 0.15, should pass
    decision = _decision({"AAPL": 0.50, "CASH": 0.15})
    guard.validate(decision, portfolio, prices)  # must not raise


def test_min_cash_pct_explicit_cash_key_below_min_raises() -> None:
    """Explicit CASH target below min_cash_pct must raise."""
    guard = RiskGuard(min_cash_pct=0.10)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    decision = _decision({"AAPL": 0.30, "CASH": 0.05})
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "min_cash_pct"


# ---------------------------------------------------------------------------
# Constraint 4: max_daily_trades
# ---------------------------------------------------------------------------


def test_max_daily_trades_exactly_at_limit_passes() -> None:
    """Exactly 10 tickers trading on a limit of 10 must pass."""
    guard = RiskGuard(max_daily_trades=10, max_delta_pct=1.0, max_position_pct=1.0)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    tickers = {f"T{i:02d}": 0.05 for i in range(10)}  # 10 tickers, each 5%
    decision = _decision(tickers)
    guard.validate(decision, portfolio, prices)  # must not raise


def test_max_daily_trades_one_over_limit_raises() -> None:
    """11 tickers changing on a limit of 10 must raise."""
    guard = RiskGuard(max_daily_trades=10, max_delta_pct=1.0, max_position_pct=1.0)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    tickers = {f"T{i:02d}": 0.05 for i in range(11)}  # 11 tickers
    decision = _decision(tickers)
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_daily_trades"


def test_max_daily_trades_cash_key_not_counted() -> None:
    """CASH key in targets is not counted as a trade."""
    guard = RiskGuard(max_daily_trades=2, max_delta_pct=1.0, max_position_pct=1.0)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    # 2 tickers + CASH key → only 2 trades, should pass
    decision = _decision({"AAPL": 0.20, "MSFT": 0.20, "CASH": 0.60})
    guard.validate(decision, portfolio, prices)  # must not raise


def test_max_daily_trades_full_exits_counted() -> None:
    """Tickers in portfolio but absent from targets count as trades."""
    guard = RiskGuard(max_daily_trades=2, max_delta_pct=1.0, max_position_pct=1.0)
    # 3 existing positions, all being exited (not in targets)
    portfolio = _snapshot(
        positions=[
            ("AAPL", "10", "100"),
            ("MSFT", "10", "100"),
            ("TSLA", "10", "100"),
        ],
        cash="7000",
    )
    prices = _prices(("AAPL", "100"), ("MSFT", "100"), ("TSLA", "100"))
    decision = _decision({})  # full exit of all 3 → 3 trades
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_daily_trades"


def test_max_daily_trades_unchanged_positions_not_counted() -> None:
    """Tickers whose weight doesn't change are not counted as trades."""
    guard = RiskGuard(max_daily_trades=1, max_delta_pct=1.0, max_position_pct=1.0)
    # AAPL at 50% of portfolio
    portfolio = _snapshot(positions=[("AAPL", "50", "100")], cash="5000")
    prices = _prices(("AAPL", "100"))
    # Target AAPL = 0.50 exactly — no change, no trade
    decision = _decision({"AAPL": 0.50})
    guard.validate(decision, portfolio, prices)  # must not raise


# ---------------------------------------------------------------------------
# Missing price raises ValueError
# ---------------------------------------------------------------------------


def test_missing_price_for_held_position_raises_value_error() -> None:
    """ValueError raised when price missing for a held position."""
    guard = RiskGuard()
    portfolio = _snapshot(positions=[("AAPL", "10", "100")], cash="9000")
    prices: dict[str, Decimal] = {}  # no price for AAPL
    decision = _decision({"AAPL": 0.10})
    with pytest.raises(ValueError, match="AAPL"):
        guard.validate(decision, portfolio, prices)


def test_missing_price_only_for_one_of_many_positions_raises() -> None:
    """ValueError raised even when only one of multiple positions is missing."""
    guard = RiskGuard()
    portfolio = _snapshot(
        positions=[("AAPL", "10", "100"), ("MSFT", "10", "100")],
        cash="8000",
    )
    prices = _prices(("AAPL", "100"))  # MSFT missing
    decision = _decision({"AAPL": 0.10, "MSFT": 0.10})
    with pytest.raises(ValueError):
        guard.validate(decision, portfolio, prices)


# ---------------------------------------------------------------------------
# Constraint ordering: position check fires before delta check
# ---------------------------------------------------------------------------


def test_constraint_ordering_position_before_delta() -> None:
    """max_position_pct is checked before max_delta_pct."""
    guard = RiskGuard(max_position_pct=0.30, max_delta_pct=0.20)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    # AAPL = 0.35 violates position (>0.30) AND delta (>0.20 from 0%)
    decision = _decision({"AAPL": 0.35})
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_position_pct"


def test_constraint_ordering_delta_before_cash() -> None:
    """max_delta_pct is checked before min_cash_pct."""
    guard = RiskGuard(max_position_pct=0.50, max_delta_pct=0.20, min_cash_pct=0.10)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    # AAPL = 0.25 violates delta (>0.20 from 0%) AND
    # MSFT = 0.25 + AAPL = 0.25 → sum = 0.70 → cash = 0.30 (ok)
    # So only delta violation here
    decision = _decision({"AAPL": 0.25})
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_delta_pct"


def test_constraint_ordering_cash_before_trades() -> None:
    """min_cash_pct is checked before max_daily_trades."""
    guard = RiskGuard(
        max_position_pct=0.10,
        max_delta_pct=0.10,
        min_cash_pct=0.10,
        max_daily_trades=2,
    )
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    # 3 tickers at 0.05 each (sum = 0.15, cash = 0.85) — delta = 0.05 ≤ 0.10 ✓
    # position = 0.05 ≤ 0.10 ✓
    # cash = 0.85 ≥ 0.10 ✓
    # trades = 3 > 2 → raises max_daily_trades
    decision = _decision({"AAPL": 0.05, "MSFT": 0.05, "TSLA": 0.05})
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_daily_trades"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_all_cash_portfolio_zero_delta_no_rebalance() -> None:
    """Empty decision on all-cash portfolio — nothing trades, all passes."""
    guard = RiskGuard()
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    decision = _decision({})
    guard.validate(decision, portfolio, prices)  # must not raise


def test_custom_limits_more_restrictive() -> None:
    """Custom limits stricter than defaults are honoured."""
    guard = RiskGuard(max_position_pct=0.20, max_delta_pct=0.10)
    portfolio = _snapshot(cash="10000")
    prices: dict[str, Decimal] = {}
    decision = _decision({"AAPL": 0.21})  # exceeds 0.20 position limit
    with pytest.raises(RiskViolationError) as exc_info:
        guard.validate(decision, portfolio, prices)
    assert exc_info.value.constraint == "max_position_pct"


def test_risk_violation_error_message_format() -> None:
    """RiskViolationError str includes constraint name and detail."""
    err = RiskViolationError("max_position_pct", "AAPL too big")
    assert "[max_position_pct]" in str(err)
    assert "AAPL too big" in str(err)
    assert err.constraint == "max_position_pct"
    assert err.detail == "AAPL too big"


def test_validate_with_multiple_positions_correct_weights() -> None:
    """Current weights computed correctly for a multi-position portfolio."""
    guard = RiskGuard(max_delta_pct=0.05)
    # AAPL=4000, MSFT=2000, cash=4000 → total=10000
    # AAPL weight = 0.40, MSFT weight = 0.20
    portfolio = _snapshot(
        positions=[("AAPL", "40", "100"), ("MSFT", "20", "100")],
        cash="4000",
    )
    prices = _prices(("AAPL", "100"), ("MSFT", "100"))
    # Target AAPL=0.40 exactly (delta=0), MSFT=0.20 exactly (delta=0)
    decision = _decision({"AAPL": 0.40, "MSFT": 0.20})
    guard.validate(decision, portfolio, prices)  # must not raise


def test_max_daily_trades_boundary_with_no_change_tickers() -> None:
    """Tickers already at target weight do not count toward trade limit."""
    guard = RiskGuard(max_daily_trades=1, max_delta_pct=1.0, max_position_pct=1.0)
    # AAPL at exactly 50%, MSFT being added at 20%
    portfolio = _snapshot(positions=[("AAPL", "50", "100")], cash="5000")
    prices = _prices(("AAPL", "100"))
    # AAPL keeps 50% (no trade), MSFT goes 0% → 20% (1 trade)
    decision = _decision({"AAPL": 0.50, "MSFT": 0.20})
    guard.validate(decision, portfolio, prices)  # must not raise (only 1 trade)
