FROM python:3.12-slim-bookworm

# Dependencias del sistema para Playwright/Chromium (Debian 12 Bookworm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates \
    libnss3 libnspr4 libdbus-1-3 \
    libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 \
    libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 \
    libxshmfence1 libx11-6 libxext6 \
    fonts-liberation fonts-unifont \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar Chromium (sin install-deps, ya están instaladas arriba)
RUN playwright install chromium

COPY bot.py .

CMD ["python", "bot.py"]
