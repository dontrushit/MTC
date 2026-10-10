VENV := .venv
PY := $(VENV)/bin/python

.PHONY: setup lint test test-slow check run

setup:
	scripts/setup.sh

lint:
	$(PY) -m ruff check .

test:
	$(PY) -m pytest -q

test-slow:
	$(PY) -m pytest -m slow -q

check:
	$(PY) scripts/check_env.py

run:
	scripts/run.sh
