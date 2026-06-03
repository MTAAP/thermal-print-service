.PHONY: verify verify-all test test-all lint typecheck core-test core-lint core-typecheck service-test mcp-test service-lint mcp-lint service-typecheck mcp-typecheck design-test design-test-all design-lint design-typecheck hub-test hub-lint hub-typecheck

CORE_PY ?= printer-core/.venv/bin/python
SERVICE_PY ?= service/.venv/bin/python
MCP_PY ?= mcp-server/.venv/bin/python
DESIGN_PY ?= design/.venv/bin/python
# The hub package and its project dir share the name `hub`, so the project dir
# shadows the installed package on sys.path from the repo root. Run all hub
# Python from inside hub/ (CWD=hub) so `import hub` resolves to the package.
HUB_PY ?= .venv/bin/python

verify: test lint typecheck

# Full gate — runs the slow Playwright design tests too. Use before
# pushing to main; the fast `verify` target excludes them so the local
# loop stays under a few seconds.
verify-all: test-all lint typecheck

test: core-test service-test mcp-test hub-test design-test

test-all: core-test service-test mcp-test hub-test design-test-all

lint: core-lint service-lint mcp-lint hub-lint design-lint

typecheck: core-typecheck service-typecheck mcp-typecheck hub-typecheck design-typecheck

core-test:
	$(CORE_PY) -m pytest printer-core/tests

core-lint:
	$(CORE_PY) -m ruff check printer-core/printer_core printer-core/tests

core-typecheck:
	$(CORE_PY) -m mypy printer-core/printer_core

service-test:
	$(SERVICE_PY) -m pytest service/tests

mcp-test:
	$(MCP_PY) -m pytest mcp-server/tests

service-lint:
	$(SERVICE_PY) -m ruff check service

mcp-lint:
	$(MCP_PY) -m ruff check mcp-server

service-typecheck:
	$(SERVICE_PY) -m mypy --config-file service/pyproject.toml service/printer

mcp-typecheck:
	$(MCP_PY) -m mypy --config-file mcp-server/pyproject.toml mcp-server/printer_mcp

# Hub targets cd into hub/ first (see HUB_PY note above): the project dir
# shadows the `hub` package on sys.path when run from the repo root.
hub-test:
	cd hub && $(HUB_PY) -m pytest tests

hub-lint:
	cd hub && $(HUB_PY) -m ruff check hub tests

hub-typecheck:
	cd hub && $(HUB_PY) -m mypy hub

design-test:
	$(DESIGN_PY) -m pytest design/tests -m "not slow"

design-test-all:
	$(DESIGN_PY) -m pytest design/tests

design-lint:
	$(DESIGN_PY) -m ruff check design/tprint_design design/tests

design-typecheck:
	$(DESIGN_PY) -m mypy --config-file design/pyproject.toml design/tprint_design
