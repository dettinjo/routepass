FROM python:3.11-slim

# Set build-time env vars
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (for building some wheels if necessary)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Build context is the monorepo root so we can include shared/
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY backend/ .

# Copy shared assets (sport-mappings.json etc.) to the location the app expects
COPY shared/ /shared/

# Explicitly use python -m uvicorn for consistency
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
