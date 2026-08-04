FROM mcr.microsoft.com/playwright:v1.45.0-jammy

WORKDIR /app

# Install Chromium
RUN apt-get update && apt-get install -y \
    chromium-browser \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Start Xvfb + Chromium + Celery worker
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x1024x24 & \
    chromium-browser --remote-debugging-port=9222 --no-sandbox --disable-dev-shm-usage --user-data-dir=/data/chrome-profiles & \
    python -m celery -A app.celery_app worker -Q publish -c 1 -l info"]
