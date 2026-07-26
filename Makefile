.PHONY: install-dev format lint type-check test

install-dev:
	pip install -e ".[dev]"

format:
	ruff format action_quality_alerting/ tests/ scripts/
	ruff check action_quality_alerting/ tests/ scripts/ --fix

lint:
	ruff check action_quality_alerting/ tests/ scripts/

type-check:
	mypy action_quality_alerting/

test:
	pytest
