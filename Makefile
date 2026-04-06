.PHONY: dev test lint fmt clean

dev:
	uvicorn app.main:app --reload --port 8000

worker:
	arq app.workers.analyzer.WorkerSettings

test:
	pytest -v --tb=short

test-cov:
	pytest --cov=app --cov-report=html --cov-report=term

lint:
	ruff check .
	mypy app/

fmt:
	ruff format .
	ruff check --fix .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache htmlcov .coverage dist build *.egg-info
