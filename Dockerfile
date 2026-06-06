FROM python:3.12-slim-bookworm

# ── Todas las dependencias que Chromium/Playwright necesita ────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core Chromium
    libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 \
    # Pango / Cairo (renderizado de texto y gráficos)
    libpango-1.0-0 libpangocairo-1.0-0 \
    libcairo2 libcairo-gobject2 \
    # Extras
    libglib2.0-0 libdbus-1-3 \
    libx11-6 libx11-xcb1 libxcb1 libxext6 \
    libxss1 libxtst6 \
    # Fuentes
    fonts-liberation fonts-noto-color-emoji \
    # Utilidades
    ca-certificates wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python deps ────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Playwright: solo Chromium ──────────────────────────────────
RUN playwright install chromium

# ── Código ─────────────────────────────────────────────────────
COPY bot.py .

RUN mkdir -p /app/gm_session

CMD ["python", "bot.py"]
