FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY rss_glue ./rss_glue

# Install the project itself
RUN uv sync --frozen --no-dev


FROM python:3.11-slim

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy static files
COPY static /app/static

# Copy application code
COPY --from=builder /app/rss_glue ./rss_glue

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV ENABLE_BACKGROUND_WORKER=true
ENV MEDIA_DIR=/var/media

# Create non-root user and data directories
RUN useradd --create-home --uid 1000 rssglue && \
    mkdir -p /var/data /var/media && \
    chown -R rssglue:rssglue /var/data /var/media /app

VOLUME ["/var/data", "/var/media"]

# Switch to non-root user
USER rssglue

# Set working directory to data so database is stored in volume
WORKDIR /var/data

EXPOSE 8000

CMD ["uvicorn", "rss_glue.main:app", "--host", "0.0.0.0", "--port", "8000"]
