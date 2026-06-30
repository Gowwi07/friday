# FRIDAY Backend — Dockerfile
# Multi-stage build for Google Cloud Run

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Cloud Run sets PORT env var (default 8080)
ENV PORT=8080
ENV APP_ENV=production

# Run the FastAPI app with uvicorn
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1
