FROM python:3.12-slim-bookworm

# ── Dependencias del sistema para Chromium/Playwright ──────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chromium core
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 \
    # Fuentes (necesario para renderizar texto en páginas)
    fonts-liberation fonts-noto-color-emoji \
    # Extras de estabilidad
    ca-certificates wget curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python deps ────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Playwright: instalar solo Chromium (sin deps del SO, ya están arriba) ──
RUN playwright install chromium

# ── Código ─────────────────────────────────────────────────────
COPY bot.py .

# Carpeta de sesión persistente
RUN mkdir -p /app/gm_session

CMD ["python", "bot.py"]
