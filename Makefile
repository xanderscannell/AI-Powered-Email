.PHONY: install run test lint format typecheck check clean

# ── Setup ──────────────────────────────────────────────────────────────────────
install:
	uv sync --extra dev

# ── Run ────────────────────────────────────────────────────────────────────────
run:
	uv run python -m src

# ── Testing ────────────────────────────────────────────────────────────────────
test:
	uv run pytest tests/

coverage:
	uv run pytest --cov=src --cov-report=term-missing tests/

# ── Linting & Formatting ───────────────────────────────────────────────────────
format:
	uv run black src/ tests/
	uv run ruff check --fix src/ tests/

lint:
	uv run ruff check src/ tests/
	uv run black --check src/ tests/

typecheck:
	uv run mypy src/

# Run all checks (lint + typecheck + tests)
check: lint typecheck test

# ── Cleanup ────────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
