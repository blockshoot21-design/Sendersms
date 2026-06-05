# 📨 Google Messages Bulk Sender — Telegram Bot v1

Bot de Telegram que envía mensajes masivos por Google Messages (SMS/RCS)
usando Playwright. Abre **10 páginas en paralelo** para enviar 10 mensajes
a la vez.

---

## 🚀 Instalación y uso local

```bash
# 1. Instalar dependencias Python
pip install python-telegram-bot playwright

# 2. Instalar navegador Chromium
playwright install chromium

# 3. Editar bot.py → pon tu BOT_TOKEN y ALLOWED_USER
#    BOT_TOKEN    = "123456:ABC-DEF..."   # De @BotFather
#    ALLOWED_USER = "TuUsername"          # Tu @ de Telegram (sin @)

# 4. Ejecutar
python bot.py

# O en segundo plano (Linux/macOS):
nohup python bot.py > bot.log 2>&1 &
```

---

## 🐳 Despliegue con Docker

```bash
docker build -t gmsg-bot .
docker run -d --name gmsg-bot \
  -v $(pwd)/gm_session:/app/gm_session \
  gmsg-bot
```

---

## 📱 Flujo del bot

| Paso | Acción |
|------|--------|
| `/start` | Menú principal |
| 📱 Conectar | El bot abre Chromium y manda el QR de Google Messages |
| Escanear QR | Abre Google Messages en el móvil → Mensajes para web → Escanear |
| 📨 Enviar mensajes | Pide el archivo .txt con contactos (uno por línea) |
| ✏️ Mensaje | Escribe el texto a enviar |
| ✅ Confirmar | El bot abre **10 páginas en paralelo** y envía 10 mensajes a la vez |
| 🏁 Resultado | Resumen de enviados/fallidos |

---

## ⚙️ Configuración en bot.py

| Variable | Descripción |
|----------|-------------|
| `BOT_TOKEN` | Token de @BotFather |
| `ALLOWED_USER` | Username de Telegram (sin @). Usa `"*"` para todos |
| `PAIS_PREFIJO` | Prefijo por defecto (ej: `"+34"` para España) |
| `NUM_PAGINAS` | Páginas paralelas (default: 10) |
| `PAUSA_ENVIO` | Segundos entre mensajes (sube si Google bloquea) |
| `SESSION_DIR` | Carpeta donde se guarda la sesión de Google |

---

## 📄 Formato archivo .txt

```
612345678
+34623456789
0034634567890
612 345 678
```

Un número por línea. El bot normaliza automáticamente a formato E.164.

---

## ⚠️ Notas

- La sesión de Google Messages se guarda en `./gm_session` — no hay que volver a escanear el QR en cada reinicio.
- Si Google Messages bloquea, aumenta `PAUSA_ENVIO` o reduce `NUM_PAGINAS`.
- Compatible con Railway, Render, VPS o cualquier servidor con Python 3.12+.
