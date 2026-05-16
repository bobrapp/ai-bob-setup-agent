# AIGovOps Foundation Automation — Production Dockerfile
# Multi-stage build for minimal image size

FROM python:3.12-slim AS base

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directories
RUN mkdir -p data logs backups

# Non-root user
RUN useradd -m -s /bin/bash aigovops && chown -R aigovops:aigovops /app
USER aigovops

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Expose API port
EXPOSE 8000

# Default: run the Telegram bot (no HTTP needed for bot polling)
CMD ["python", "scripts/run_bot.py"]
