

run_coverage:
	poetry run pytest tests/ \
		--cov=fastapi_cachemate \
		--cov-report=term-missing \
		--cov-fail-under=90

bandit:
	poetry run bandit -r app

mypy:
	poetry run mypy .

ruff:
	poetry run ruff check .

ruff-format:
	poetry run ruff format . --check

linters: mypy bandit ruff ruff-format
