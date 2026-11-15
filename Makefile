SHELL := /bin/bash
PY := .venv/bin/python
PIP := .venv/bin/pip
ENV ?= dev
HELM ?= helm

.PHONY: install api worker ui test e2e sample build-ui docker-build docker-up docker-down docker-logs migrate revision \
	provision-init provision-doctor provision-plan provision-apply helm-lint helm-template test-provision

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

test-provision:
	$(PY) -m pytest scripts/tests -q

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

# Provisionamento em Kubernetes (local, on-prem ou nuvem)
e2e:
	$(PY) scripts/e2e.py --token "$(TOKEN)" --video $(VIDEO)

provision-init:
	$(PY) scripts/provision.py init --env $(ENV)

provision-doctor:
	$(PY) scripts/provision.py doctor --env $(ENV)

provision-plan:
	$(PY) scripts/provision.py plan --env $(ENV)

provision-apply:
	$(PY) scripts/provision.py apply --env $(ENV)

helm-lint:
	$(HELM) lint deploy/helm/openoju

helm-template:
	$(HELM) template openoju deploy/helm/openoju -f deploy/helm/openoju/values-minimal.yaml
