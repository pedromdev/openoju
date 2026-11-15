SHELL := /bin/bash
PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: install api worker ui test sample build-ui docker-build docker-up docker-down docker-logs migrate revision

install:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements-dev.txt
	cd frontend && npm ci

migrate:
	.venv/bin/alembic upgrade head

revision:
	.venv/bin/alembic revision --autogenerate -m "$(m)"

api:
	PYTHONPATH=backend $(PY) -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

worker:
	PYTHONPATH=backend $(PY) -m app.worker

ui:
	cd frontend && npm start

test:
	PYTHONPATH=backend $(PY) -m pytest backend/tests -q

sample:
	./scripts/make_sample.sh

build-ui:
	cd frontend && npm run build

docker-build:
	docker compose build

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f --tail=100
