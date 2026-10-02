# ShadowFlow backend API (FastAPI) - deployed to Render via render.yaml.
#
# Multi-stage to keep the shipped image small: dependencies are resolved into
# /opt/venv in a builder stage, and the runtime stage copies only that venv
# plus the app (no pip, no build residue, no test-only tooling).
# Runtime requirements exclude test deps (see requirements-dev.txt).

# ---- builder: resolve + install pinned runtime deps into a venv -----------
FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
# Install, then drop pip/setuptools (~30 MB) BEFORE the venv is copied - doing
# it in the runtime stage would only white out files, not reclaim layer bytes.
RUN pip install -r requirements.txt \
    && python -m pip uninstall -y pip setuptools > /dev/null 2>&1 || true

# ---- runtime: ship only the venv + the application ----------------------
FROM python:3.11-slim
# Headless matplotlib so the dossier ring image renders without a display.
ENV MPLBACKEND=Agg \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Includes engine/, main.py, generate_data.py and the committed data/ CSVs +
# ground_truth.json (regenerated only if missing at startup).
COPY . .

# Precompile app bytecode and warm the matplotlib font cache at BUILD time so
# a cold container starts serving sooner.
RUN python -m compileall -q main.py generate_data.py engine > /dev/null 2>&1 || true \
    && python -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot"

EXPOSE 8000

# Shell form so ${PORT:-8000} expands (Render sets PORT; default 8000 locally).
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}