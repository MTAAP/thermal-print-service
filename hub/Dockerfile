# Hub image for the thermal-print friend network, built + deployed on Railway.
#
# constraints.txt mirrors the dev venv built under the >=48h release-age gate, so
# the image build resolves NO fresh (potentially-malicious) releases. Installing
# with `-c constraints.txt` pins every version to that vetted set while pip still
# installs only the genuine runtime closure -- dev-only pins (pytest, mypy and its
# mypyc bits, ruff) are never pulled into the image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HUB_HOST=0.0.0.0

WORKDIR /app

# Only what pip needs to build + resolve. Tests, caches and the local .venv are
# kept out of the build context by .dockerignore.
COPY pyproject.toml README.md constraints.txt ./
COPY hub ./hub

RUN pip install -c constraints.txt .

# uvicorn binds 0.0.0.0:$PORT (Railway injects PORT); see hub/cli.py.
CMD ["printer-hub", "run"]
