FROM mcr.microsoft.com/playwright:v1.45.0-jammy

WORKDIR /app

# Install Chromium + supervisord + python3-pip
RUN apt-get update && apt-get install -y \
    chromium-browser \
    xvfb \
    python3-pip \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 --version

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

# Copy supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Use supervisord to manage processes
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
