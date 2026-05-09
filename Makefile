.PHONY: verify test lint typecheck service-test mcp-test service-lint mcp-lint service-typecheck mcp-typecheck

SERVICE_PY ?= service/.venv/bin/python
MCP_PY ?= mcp-server/.venv/bin/python

verify: test lint typecheck

test: service-test mcp-test

lint: service-lint mcp-lint

typecheck: service-typecheck mcp-typecheck

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
