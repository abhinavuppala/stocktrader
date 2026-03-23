# StockTrader — Project Lessons

Project-specific lessons: architecture decisions, library quirks, debugging notes.

---

## ruff UP042: use `StrEnum` instead of `(str, Enum)`
Python 3.11+ has `enum.StrEnum`; ruff's UP042 rule flags `class Foo(str, Enum)` as fixable. Always use `from enum import StrEnum` and `class Foo(StrEnum)` to avoid the warning.

## ruff UP035: `Callable` belongs in `collections.abc`, not `typing`
Python 3.9+ deprecates `typing.Callable` in favour of `collections.abc.Callable`. Import from `collections.abc` to satisfy UP035 without needing `--unsafe-fixes`.

## ruff I001: isort enforced — always run `ruff check --fix` after writing new files
ruff's I001 rule flags unsorted imports even when they look correct by eye (e.g. `Decimal, ROUND_DOWN` vs `ROUND_DOWN, Decimal`). Running `ruff check --fix` after writing new files is the fastest remediation.

## RiskGuard defaults must be permissive (1.0/1.0/0.0) so constraint-isolation tests work
Pre-written tests for `min_cash_pct` used AAPL=0.50 with only `min_cash_pct` overridden, expecting position/delta constraints not to fire. Setting `RiskGuard` defaults to `max_position_pct=1.0`, `max_delta_pct=1.0`, `min_cash_pct=0.0` resolves this; every constraint test that needs a specific limit sets it explicitly.

## StateManager fill ordering: create fills with explicit distinct timestamps in tests
Two fills inserted in rapid succession may share the same `datetime.now(UTC)` timestamp. Tests asserting DESC ordering must construct `Fill` objects with explicit `filled_at` values spaced by `timedelta(seconds=1)` to guarantee deterministic ordering.

## StateManager.get_portfolio_snapshot was missing — added as _rebuild_portfolio_snapshot
The method was not implemented in `state_manager.py` even though tests called it. When adding it, also import `PortfolioSnapshot` and `Position` from `stocktrader.trading.models`. The underscore prefix signals it is an internal DB rebuild, not the public broker API path.

## GitHub Actions CI: use `uv python install` explicitly before `uv sync`
When using `astral-sh/setup-uv@v5`, call `uv python install 3.12` as a separate step before `uv sync --group dev` to ensure the exact Python version is pinned; relying solely on the runner's system Python can lead to version mismatches.
