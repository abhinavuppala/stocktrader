# StockTrader — Claude Code Instructions

## Project Overview
Sentiment-driven algorithmic paper trading system. See the full architecture plan at `C:\Users\abhin\.claude\plans\kind-popping-galaxy.md`.

**Current phase:** Phase 1 — Foundations (StateManager, MockBroker, IBroker, PositionManager, RiskGuard, CI)

## Tool Usage
Follow global rules: use `Glob`, `Grep`, `Read` instead of Bash for file operations. See `~/.claude/CLAUDE.md`.

## Stack
- Python 3.12+, `uv` for package management (`uv sync`, `uv run pytest`, `uv run mypy src`)
- pydantic v2, SQLAlchemy 2.0 async + aiosqlite, structlog, httpx
- ruff + mypy --strict enforced via pre-commit

## Key Conventions
- All data models use pydantic v2 with strict validation
- All public functions must have type annotations passing `mypy --strict`
- Mock at the boundary (Anthropic API, Finnhub, Alpaca) — never mock internal code in tests
- `IBroker` is the load-bearing interface — both `MockBroker` and `AlpacaBroker` implement it; never couple calling code to a concrete broker
- `RiskGuard` must sit between any LLM/agent decision and the broker — non-negotiable

## Running Things
```bash
uv run pytest                     # run all tests
uv run pytest tests/unit          # unit tests only
uv run mypy src                   # type check
uv run ruff check .               # lint
uv run ruff format .              # format
python scripts/backtest.py        # run historical simulation (Phase 1+)
```

## Lessons & Reflection
- **Before tackling any issue**, scan `LESSONS.md` (this project) and `~/.claude/LESSONS.md` (global) first.
- **After completing any non-trivial task**, reflect and write 1-2 sentences to `LESSONS.md` if something went wrong, required correction, or worked particularly well. If unsure whether a lesson belongs here or in the global file, ask.
