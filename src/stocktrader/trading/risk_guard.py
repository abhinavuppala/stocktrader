from __future__ import annotations

from decimal import Decimal

from stocktrader.trading.models import PortfolioSnapshot, RebalanceDecision


class RiskViolationError(Exception):
    def __init__(self, constraint: str, detail: str) -> None:
        self.constraint = constraint
        self.detail = detail
        super().__init__(f"[{constraint}] {detail}")


class RiskGuard:
    def __init__(
        self,
        max_position_pct: float = 1.0,
        max_delta_pct: float = 1.0,
        min_cash_pct: float = 0.0,
        max_daily_trades: int = 100,
    ) -> None:
        self.max_position_pct = max_position_pct
        self.max_delta_pct = max_delta_pct
        self.min_cash_pct = min_cash_pct
        self.max_daily_trades = max_daily_trades

    def validate(
        self,
        decision: RebalanceDecision,
        portfolio: PortfolioSnapshot,
        prices: dict[str, Decimal],
    ) -> None:
        """Validate a RebalanceDecision against the current portfolio and prices.

        Raises RiskViolationError on the first constraint violation.
        Raises ValueError if a price is missing for a held position.
        Returns None if all checks pass.
        """
        # Build a lookup map for positions
        position_map: dict[str, Decimal] = {
            p.ticker: p.quantity for p in portfolio.positions
        }

        # Validate that prices are present for all held positions
        for ticker in position_map:
            if ticker not in prices:
                raise ValueError(
                    f"No price available for held position: {ticker}"
                )

        # Compute total portfolio value
        equity_value = sum(
            position_map[ticker] * prices[ticker] for ticker in position_map
        )
        total_value = portfolio.cash + equity_value

        # Compute current weights (avoid division by zero on empty portfolio)
        current_weights: dict[str, float] = {}
        if total_value > Decimal("0"):
            for ticker, qty in position_map.items():
                current_weights[ticker] = float(
                    qty * prices[ticker] / total_value
                )
            current_weights["CASH"] = float(portfolio.cash / total_value)
        else:
            current_weights["CASH"] = 1.0

        # --- Constraint 1: max_position_pct ---
        for ticker, target_weight in decision.targets.items():
            if ticker == "CASH":
                continue
            if target_weight > self.max_position_pct + 1e-9:
                raise RiskViolationError(
                    "max_position_pct",
                    f"{ticker} target weight {target_weight:.6f} exceeds "
                    f"max allowed {self.max_position_pct:.6f}",
                )

        # --- Constraint 2: max_delta_pct ---
        for ticker, target_weight in decision.targets.items():
            if ticker == "CASH":
                continue
            current_weight = current_weights.get(ticker, 0.0)
            delta = abs(target_weight - current_weight)
            if delta > self.max_delta_pct + 1e-9:
                raise RiskViolationError(
                    "max_delta_pct",
                    f"{ticker} weight delta {delta:.6f} exceeds "
                    f"max allowed {self.max_delta_pct:.6f}",
                )

        # Also check tickers in portfolio but not in decision targets (full sell)
        for ticker in position_map:
            if ticker == "CASH" or ticker in decision.targets:
                continue
            # Target weight is 0 (full exit)
            current_weight = current_weights.get(ticker, 0.0)
            delta = abs(0.0 - current_weight)
            if delta > self.max_delta_pct + 1e-9:
                raise RiskViolationError(
                    "max_delta_pct",
                    f"{ticker} weight delta {delta:.6f} exceeds "
                    f"max allowed {self.max_delta_pct:.6f} (full exit)",
                )

        # --- Constraint 3: min_cash_pct ---
        # Implied cash = 1.0 - sum of all non-cash target weights
        non_cash_weight = sum(
            w for t, w in decision.targets.items() if t != "CASH"
        )
        # If CASH is explicitly in targets, use it; otherwise infer it
        if "CASH" in decision.targets:
            implied_cash = decision.targets["CASH"]
        else:
            implied_cash = 1.0 - non_cash_weight

        if implied_cash < self.min_cash_pct - 1e-9:
            raise RiskViolationError(
                "min_cash_pct",
                f"Implied cash allocation {implied_cash:.6f} is below "
                f"minimum required {self.min_cash_pct:.6f}",
            )

        # --- Constraint 4: max_daily_trades ---
        # Count tickers being traded: either in targets (and changing) or
        # in positions but not in targets (full sell)
        trades: set[str] = set()

        for ticker, target_weight in decision.targets.items():
            if ticker == "CASH":
                continue
            current_weight = current_weights.get(ticker, 0.0)
            # A trade occurs if the weight changes meaningfully
            if abs(target_weight - current_weight) > 1e-9:
                trades.add(ticker)

        for ticker in position_map:
            if ticker == "CASH" or ticker in decision.targets:
                continue
            # Full exit — always a trade if there's a position
            if current_weights.get(ticker, 0.0) > 1e-9:
                trades.add(ticker)

        if len(trades) > self.max_daily_trades:
            raise RiskViolationError(
                "max_daily_trades",
                f"{len(trades)} tickers being traded exceeds "
                f"max allowed {self.max_daily_trades}",
            )
