.PHONY: verify test lint typecheck core-test core-lint core-typecheck service-test mcp-test service-lint mcp-lint service-typecheck mcp-typecheck

CORE_PY ?= printer-core/.venv/bin/python
SERVICE_PY ?= service/.venv/bin/python
MCP_PY ?= mcp-server/.venv/bin/python

verify: test lint typecheck

test: core-test service-test mcp-test

lint: core-lint service-lint mcp-lint

typecheck: core-typecheck service-typecheck mcp-typecheck

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
	$(MCP_PY) -m mypy mcp-server/printer_mcp
