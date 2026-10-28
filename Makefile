.PHONY: install lint test run

install:
	uv sync --extra dev

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest

run:
	uv run atlas
