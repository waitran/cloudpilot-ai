PYTHON ?= python3.12
UV ?= uv

.PHONY: init install up down logs restart migrate status check test smoke
init:
	$(PYTHON) scripts/init_env.py

install:
	$(UV) sync --project backend --locked
	cd frontend && npm ci

up: init
	docker compose up --build --wait --wait-timeout 180

down:
	docker compose down

logs:
	docker compose logs --follow --tail=100

restart:
	docker compose restart backend frontend worker

migrate:
	docker compose run --rm migrate

status:
	docker compose ps

check:
	$(PYTHON) scripts/check_repository.py
	$(UV) run --project backend ruff check backend scripts tests
	$(UV) run --project backend ruff format --check backend scripts tests
	cd frontend && npm run lint && npm run format:check && npm run typecheck
	git diff --check
	git diff --cached --check

test:
	$(PYTHON) -m unittest discover -s tests -v
	$(UV) run --project backend pytest backend/tests
	cd frontend && npm test

smoke:
	$(PYTHON) scripts/smoke_http.py
	$(PYTHON) scripts/smoke_collection.py
