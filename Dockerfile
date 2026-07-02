# AstroWebEngine — container image
# Builds a self-contained server; data (SQLite + WAL) persists on a mounted volume.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Persist the database on the mounted volume, not in the image layer.
    # Four slashes = absolute path. WAL/-shm sidecar files land in /data too.
    DATABASE_URL=sqlite:////data/astroclone.db

WORKDIR /app

# Dependencies first for layer caching. psycopg[binary] and bcrypt ship wheels,
# so no compiler/system packages are needed on slim.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application code (see .dockerignore for what is deliberately excluded —
# DBs, logs, _private/, uploads/, tests, docs).
COPY . .

# Non-root runtime; own /app and the data dir.
RUN useradd --create-home awe \
    && mkdir -p /data \
    && chown -R awe:awe /app /data
USER awe

EXPOSE 8000

# Liveness via the public version endpoint (no curl in the image).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/version')" || exit 1

CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8000"]
