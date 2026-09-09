# Guestbook image: the one-tool MCP server that lets a stranger send the owner a
# printed note. Built and run beside the chat host that talks to it.
#
# constraints.txt mirrors the dev venv built under the >=48h release-age gate, so
# the image build resolves NO fresh (potentially malicious) releases.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md constraints.txt ./
COPY printer_mcp ./printer_mcp

RUN pip install -c constraints.txt .

# Runs unprivileged: the process only needs to write its own quota file, and the
# state directory is a volume owned by this uid.
RUN useradd --create-home --uid 10001 guestbook \
    && mkdir -p /var/lib/printer-guestbook \
    && chown guestbook:guestbook /var/lib/printer-guestbook
USER guestbook

CMD ["printer-mcp-guestbook"]
