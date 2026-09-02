FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install \
      fastapi==0.109.0 \
      "uvicorn[standard]==0.27.0" \
      "sqlalchemy[asyncio]==2.0.25" \
      asyncpg==0.29.0 \
      psycopg2-binary==2.9.9 \
      alembic==1.13.1 \
      "pydantic==2.5.3" \
      "pydantic-settings==2.1.0" \
      "python-jose[cryptography]==3.3.0" \
      "passlib[argon2]==1.7.4" \
      argon2-cffi==23.1.0 \
      python-multipart==0.0.6 \
      slowapi==0.1.9 \
      structlog==24.1.0 \
      prometheus-client==0.20.0 \
      email-validator==2.1.0 \
      httpx==0.26.0 \
      redis==5.0.1

# Copy source
COPY app ./app
COPY scripts ./scripts
COPY sim ./sim
COPY alembic.ini ./

# Create non-root user
RUN useradd --create-home --shell /bin/bash avs && \
    mkdir -p /app/secrets && chown -R avs:avs /app
USER avs

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
