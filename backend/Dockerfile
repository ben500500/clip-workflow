# ============================================================
# Stage 1: Build stage - install dependencies
# ============================================================
FROM python:3.11-slim AS builder

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ============================================================
# Stage 2: Runtime stage
# ============================================================
FROM python:3.11-slim

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libpq5 \
    curl \
    fonts-noto-cjk \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /bin/false appuser

# Copy installed Python packages from builder
COPY --from=builder /root/.local /usr/local

# Set working directory
WORKDIR /app

# Copy application code
COPY . .

# Create directories for uploads and cache
RUN mkdir -p /tmp/uploads /tmp/slice_outputs /app/cache && \
    chown -R appuser:appuser /app /tmp/uploads /tmp/slice_outputs /app/cache

# Switch to non-root user
USER appuser

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

# Default command: run FastAPI with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]