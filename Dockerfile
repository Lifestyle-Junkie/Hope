FROM python:3.12-slim

# ffmpeg (music) + Playwright/Chromium system libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium browser for Playwright (required for webagent)
RUN playwright install chromium

COPY . .

ENV PORT=8080
# 2 workers so /browse-frame can answer while /ask is browsing
CMD gunicorn backend:app -b 0.0.0.0:$PORT --workers 2 --timeout 120
