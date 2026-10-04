# syntax=docker/dockerfile:1
# API image (multi-stage). Build from the repository root:
#   docker build -f backend/Dockerfile --build-arg GIT_SHA=$(git rev-parse HEAD) -t sustentra-api .
#
# Runtime stage = slim Python + a pre-built virtualenv with runtime dependencies only
# (backend/requirements.txt; dev/test tools live in requirements-dev.txt).

# ---- build: compile/install dependencies into an isolated venv ------------------
FROM python:3.12-slim AS build

# Slow / flaky connections: wait longer per read and retry instead of failing the build.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt /tmp/requirements.txt
# The cache mount keeps already-downloaded wheels between builds (including failed ones),
# so a retry resumes instead of re-downloading everything. It is not part of the image.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r /tmp/requirements.txt \
    # Trim what the runtime never needs (test suites, caches) to keep the image small.
    && find /opt/venv -depth \( -name "__pycache__" -o -name "tests" -o -name "test" \) -type d -exec rm -rf {} + \
    && find /opt/venv -name "*.pyc" -delete

# ---- runtime ---------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ARG GIT_SHA=dev
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GIT_SHA=${GIT_SHA}

WORKDIR /app

COPY --from=build /opt/venv /opt/venv

# Application code + reference data it loads at runtime.
COPY backend/ backend/
COPY contracts/ contracts/
COPY reference-data/ reference-data/

# Non-root user; /app/data is the only writable app path (mounted volume in prod).
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown app:app /app/data
USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
