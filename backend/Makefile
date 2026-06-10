.PHONY: install migrate dev test demo lint

install:
	pip install -e ".[dev]"

migrate:
	python -m alembic upgrade head

dev: migrate
	python start_server.py

test:
	pytest -q

demo:
	python -m app.autoresearch evaluate app/autoresearch/strategies/seed_strategy.py --dataset data/autoresearch/sample/backtest_sample.parquet

lint:
	ruff check .
