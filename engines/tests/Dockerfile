# 源字幕打码回归测试环境：预装 ffmpeg + opencv + numpy，避免每次 CI 重复安装
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir opencv-python-headless numpy

WORKDIR /app
