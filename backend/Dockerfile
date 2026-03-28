FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck + build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Non-root user for security
RUN useradd -m -u 1001 pyra && chown -R pyra:pyra /app
USER pyra

EXPOSE 8000

# Single worker required — route cache and simulation state are in-process.
# Multiple workers would each have their own cache, causing units to snap to
# base immediately instead of following their built routes.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--no-access-log"]