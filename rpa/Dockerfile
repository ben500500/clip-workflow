FROM mcr.microsoft.com/playwright:v1.45.0-jammy

WORKDIR /app

# Install Chromium + python3-pip（基础镜像只有 python3，无 pip）
RUN apt-get update && apt-get install -y \
    chromium-browser \
    xvfb \
    python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 --version

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

# Start Xvfb + Chromium + Celery worker
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x1024x24 & \
    chromium-browser --remote-debugging-port=9222 --no-sandbox --disable-dev-shm-usage --user-data-dir=/data/chrome-profiles & \
    python3 -m celery -A app.celery_app worker -Q publish -c 1 -l info"]
