#!/usr/bin/env python3
"""
Google Messages Bulk Sender — Telegram Bot v1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FLUJO:
  /start → Menú principal
  → [Conectar Google Messages] → Envía QR al Telegram
  → Usuario escanea QR con el móvil → Sesión vinculada
  → [Enviar mensajes] → Pide archivo .txt con contactos
  → Pide el mensaje a enviar → Confirmar
  → Abre 10 páginas en paralelo → Envía 10 mensajes a la vez

INSTALACIÓN:
  pip install python-telegram-bot playwright && playwright install chromium

USO:
  Edita BOT_TOKEN y ALLOWED_USER abajo, luego:
  python bot.py
"""

import asyncio
import base64
import io
import logging
import os
import re
import shutil
import time
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ══════════════════════════════════════════════════════════════
#  CONFIGURACIÓN — edita aquí
# ══════════════════════════════════════════════════════════════
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "8977035442:AAGA2HmaEWM7iTqNF87gAs0KJEXHhB75rGU")
ALLOWED_USER = os.environ.get("ALLOWED_USER", "K11000K")
                                         # Pon "*" para permitir a todos

PAIS_PREFIJO   = "+34"        # Prefijo por defecto para números sin código de país
PAUSA_ENVIO    = 2.0          # Segundos entre mensajes (sube si Google bloquea)
MAX_REINTENTOS = 2            # Reintentos por número antes de marcarlo como fallido
TIMEOUT_CAMPO  = 12_000       # ms para esperar campos en pantalla
TIMEOUT_NAV    = 30_000       # ms para carga de página
NUM_PAGINAS    = 10           # Páginas paralelas (10 mensajes a la vez)
SESSION_DIR    = "./gm_session"          # Carpeta de sesión persistente

URL_BASE  = "https://messages.google.com/web"
URL_NUEVA = "https://messages.google.com/web/conversations/new"
# ══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
#  ESTADO GLOBAL
# ──────────────────────────────────────────────────────────────
state: dict = {
    "phase"      : "idle",   # idle|qr|connected|wait_file|wait_msg|confirm|sending
    "chat"       : None,
    "live_msg_id": None,
    "contacts"   : [],
    "message"    : "",
    "sent"       : 0,
    "failed"     : 0,
    "total"      : 0,
    "stop"       : False,
    "pw"         : None,
    "context"    : None,
    "pages"      : [],
}

# ──────────────────────────────────────────────────────────────
#  SELECTORES
# ──────────────────────────────────────────────────────────────
SEL_PARA = (
    'input[aria-label*="Para"], '
    'input[aria-label*="To"], '
    'mws-contact-chips-autocomplete input, '
    'mws-chip-text-input input'
)
SEL_CHIP = (
    'mws-chip, mat-chip, '
    '[class*="recipient-chip"], [class*="contact-chip"], '
    '.chip-content'
)
SEL_MENSAJE = (
    'textarea[aria-label*="Mensaje"], '
    'textarea[aria-label*="Message"], '
    'textarea[aria-label*="SMS"], '
    'textarea[aria-label*="RCS"], '
    'mws-message-compose textarea'
)
SEL_ENVIAR = (
    'button[aria-label*="Enviar"], '
    'button[aria-label*="Send"], '
    'mws-message-send-button button, '
    '[data-e2e-send-button]'
)
SEL_LISTO = (
    'mws-conversations-list, '
    'button:has-text("Iniciar chat"), '
    'button:has-text("Start chat"), '
    '[data-e2e-new-conversation-button]'
)

# ──────────────────────────────────────────────────────────────
#  SCRIPT DE STEALTH — oculta señales de automatización
# ──────────────────────────────────────────────────────────────
STEALTH_SCRIPT = """
(() => {
    // Eliminar navigator.webdriver (principal señal de detección)
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true
    });

    // Simular plugins reales de Chrome
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
            ];
            plugins.refresh = () => {};
            plugins.item = (i) => plugins[i];
            plugins.namedItem = (n) => plugins.find(p => p.name === n);
            Object.setPrototypeOf(plugins, PluginArray.prototype);
            return plugins;
        }
    });

    // Idiomas reales
    Object.defineProperty(navigator, 'languages', {
        get: () => ['es-ES', 'es', 'en-US', 'en']
    });

    // Objeto window.chrome completo
    if (!window.chrome) {
        window.chrome = {
            app: { isInstalled: false, InstallState: {}, RunningState: {} },
            csi: function() {},
            loadTimes: function() {},
            runtime: {
                OnInstalledReason: {},
                OnRestartRequiredReason: {},
                PlatformArch: {},
                PlatformOs: {},
                RequestUpdateCheckStatus: {}
            }
        };
    }

    // Permisos (evita fingerprinting por permisos)
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : origQuery(parameters);
    }

    // Ocultar que es headless en User-Agent Data
    if (navigator.userAgentData) {
        Object.defineProperty(navigator, 'userAgentData', {
            get: () => ({
                brands: [
                    { brand: 'Chromium', version: '124' },
                    { brand: 'Google Chrome', version: '124' },
                    { brand: 'Not-A.Brand', version: '99' }
                ],
                mobile: false,
                platform: 'Windows'
            })
        });
    }
})();
"""

# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def normalizar(numero: str) -> str:
    """Convierte cualquier formato al formato E.164 (+XXXXXXXXXXX)."""
    limpio = re.sub(r"[^\d+]", "", numero.strip())
    if limpio.startswith("+"):
        return limpio
    if limpio.startswith("00"):
        return "+" + limpio[2:]
    if re.match(r"^[6-9]\d{8}$", limpio):          # Móvil español (9 dígitos)
        return PAIS_PREFIJO + limpio
    pais = PAIS_PREFIJO.lstrip("+")
    if limpio.startswith(pais):
        return "+" + limpio
    return "+" + limpio


def is_allowed(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    return ALLOWED_USER == "*" or user.username == ALLOWED_USER


# ──────────────────────────────────────────────────────────────
#  TECLADOS INLINE
# ──────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    rows = []
    if state["phase"] == "idle":
        rows.append([InlineKeyboardButton("📱 Conectar Google Messages", callback_data="connect")])
    elif state["phase"] == "connected":
        rows.append([InlineKeyboardButton("📨 Enviar mensajes", callback_data="send")])
        rows.append([InlineKeyboardButton("🔌 Desconectar", callback_data="disconnect")])
    else:
        rows.append([InlineKeyboardButton("🔄 Reconectar", callback_data="connect")])
    return InlineKeyboardMarkup(rows)


def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])


def kb_running() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Estado", callback_data="status"),
        InlineKeyboardButton("⛔ Detener", callback_data="stop"),
    ]])


def kb_done() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📨 Nuevo envío", callback_data="send"),
        InlineKeyboardButton("🏠 Menú", callback_data="main"),
    ]])


def kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Enviar", callback_data="confirm_send"),
        InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
    ]])


# ──────────────────────────────────────────────────────────────
#  LIVE MESSAGE (edita siempre el mismo mensaje)
# ──────────────────────────────────────────────────────────────

async def live(app: Application, chat: int, text: str,
               reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Edita el mensaje vivo existente; si falla crea uno nuevo."""
    mid = state.get("live_msg_id")
    if mid:
        try:
            await app.bot.edit_message_text(
                chat_id=chat, message_id=mid, text=text,
                parse_mode="Markdown", reply_markup=reply_markup,
            )
            return
        except Exception:
            pass
    m = await app.bot.send_message(
        chat, text, parse_mode="Markdown", reply_markup=reply_markup,
    )
    state["live_msg_id"] = m.message_id


# ══════════════════════════════════════════════════════════════
#  PLAYWRIGHT — GESTIÓN DEL NAVEGADOR
# ══════════════════════════════════════════════════════════════

async def init_browser():
    """
    Inicia Playwright con contexto persistente.
    Flags optimizados para entornos Docker/Railway sin GPU.
    Anti-detección para que Google no bloquee el renderizado.
    """
    Path(SESSION_DIR).mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()

    context = await pw.chromium.launch_persistent_context(
        SESSION_DIR,
        headless=True,
        args=[
            # ── Necesarios en Docker (sin sandbox, sin GPU) ──
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",          # /dev/shm suele ser pequeño en Docker
            "--disable-gpu",
            "--use-gl=swiftshader",             # Renderer software: canvas funciona sin GPU

            # ── Headless moderno (más parecido a browser real) ──
            "--headless=new",

            # ── Anti-detección ──
            "--disable-blink-features=AutomationControlled",
            "--disable-features=AutomationControlled",

            # ── Estabilidad ──
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-notifications",
            "--disable-infobars",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--metrics-recording-only",
            "--mute-audio",
            "--window-size=1280,900",
            "--lang=es-ES",
        ],
        viewport={"width": 1280, "height": 900},
        # User-agent de Chrome 124 real en Windows (sin "HeadlessChrome")
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="es-ES",
        timezone_id="Europe/Madrid",
        accept_downloads=True,
    )

    # Inyectar stealth en TODAS las páginas antes de que carguen
    await context.add_init_script(STEALTH_SCRIPT)

    state["pw"]      = pw
    state["context"] = context
    log.info("Navegador iniciado con stealth y swiftshader")
    return context


async def cleanup_browser():
    """Cierra el navegador y limpia el estado."""
    try:
        for p in state.get("pages", []):
            try: await p.close()
            except: pass
    except Exception:
        pass
    try:
        if state["context"]:
            await state["context"].close()
    except Exception:
        pass
    try:
        if state["pw"]:
            await state["pw"].stop()
    except Exception:
        pass
    state["pw"]      = None
    state["context"] = None
    state["pages"]   = []


async def cerrar_overlays(page) -> None:
    """Cierra popups/overlays de Google que bloqueen la UI."""
    for sel in [
        'button[aria-label="Cerrar"]',
        'button[aria-label="Close"]',
        '.cdk-overlay-pane button[aria-label*="lose"]',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.4)
                return
        except Exception:
            pass
    try:
        if await page.locator(".cdk-overlay-backdrop").count() > 0:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
    except Exception:
        pass


async def ya_autenticado(context) -> bool:
    """Comprueba rápidamente si la sesión ya está activa."""
    page = await context.new_page()
    try:
        await page.goto(URL_BASE, wait_until="domcontentloaded", timeout=TIMEOUT_NAV)
        await asyncio.sleep(2)
        count = await page.locator(SEL_LISTO).count()
        return count > 0
    except Exception:
        return False
    finally:
        try: await page.close()
        except: pass


async def esperar_autenticacion(context, timeout_s: int = 180) -> bool:
    """Sondea hasta que Google Messages esté listo (QR escaneado)."""
    page = await context.new_page()
    try:
        await page.goto(URL_BASE, wait_until="domcontentloaded", timeout=TIMEOUT_NAV)
        inicio = time.time()
        while time.time() - inicio < timeout_s:
            try:
                if await page.locator(SEL_LISTO).count() > 0:
                    return True
            except Exception:
                pass
            await asyncio.sleep(2)
        return False
    except Exception:
        return False
    finally:
        try: await page.close()
        except: pass


async def capturar_qr(context) -> bytes | None:
    """
    Abre messages.google.com, espera al canvas del QR y lo devuelve como PNG.
    Estrategia en 3 capas:
      1. JS: esperar píxeles reales en el canvas, luego toDataURL()
      2. Playwright: screenshot del elemento
      3. Screenshot completo (diagnóstico)
    """
    page = await context.new_page()
    qr_bytes = None

    try:
        log.info("Navegando a Google Messages...")
        await page.goto(URL_BASE, wait_until="domcontentloaded", timeout=TIMEOUT_NAV)

        # Esperar a que Angular arranque
        try:
            await page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # ── Clic en "Emparejar con código QR" si aparece la pantalla de bienvenida ──
        for qr_link_sel in [
            "a[href*='pair']",
            "text=Emparejar con código QR",
            "text=Pair with QR code",
            "mws-sign-in-banner a",
            "button:has-text('QR')",
        ]:
            try:
                el = page.locator(qr_link_sel).first
                if await el.count() > 0:
                    log.info("Haciendo clic en 'Emparejar con QR' (%s)", qr_link_sel)
                    await el.click()
                    await asyncio.sleep(3)
                    break
            except Exception:
                continue

        # ── Capa 1: esperar canvas con píxeles no-blancos ──────────────────
        log.info("Esperando canvas del QR con contenido real...")
        try:
            await page.wait_for_function(
                """
                () => {
                    const selectors = [
                        'mws-qr-code canvas',
                        '[data-e2e-qr-code] canvas',
                        'canvas'
                    ];
                    for (const sel of selectors) {
                        const canvas = document.querySelector(sel);
                        if (!canvas || canvas.width < 50 || canvas.height < 50) continue;
                        try {
                            const ctx = canvas.getContext('2d');
                            if (!ctx) continue;
                            const imageData = ctx.getImageData(
                                0, 0, canvas.width, canvas.height
                            );
                            const data = imageData.data;
                            // Buscar píxel oscuro (negro del QR)
                            for (let i = 0; i < data.length; i += 4) {
                                if (data[i] < 100 && data[i+1] < 100 && data[i+2] < 100
                                    && data[i+3] > 200) {
                                    return true;
                                }
                            }
                        } catch(e) { continue; }
                    }
                    return false;
                }
                """,
                timeout=25_000,
            )
            log.info("Canvas con contenido detectado, extrayendo PNG via JS...")

            data_url = await page.evaluate(
                """
                () => {
                    const selectors = [
                        'mws-qr-code canvas',
                        '[data-e2e-qr-code] canvas',
                        'canvas'
                    ];
                    for (const sel of selectors) {
                        const c = document.querySelector(sel);
                        if (c && c.width > 50) {
                            try { return c.toDataURL('image/png'); } catch(e) {}
                        }
                    }
                    return null;
                }
                """
            )

            if data_url and data_url.startswith("data:image/png;base64,"):
                raw = base64.b64decode(data_url.split(",", 1)[1])
                if len(raw) > 1000:
                    log.info("QR capturado via JS canvas (%d bytes)", len(raw))
                    qr_bytes = raw

        except Exception as e:
            log.warning("Capa 1 (JS canvas) falló: %s", e)

        # ── Capa 2: screenshot del elemento ───────────────────────────────
        if not qr_bytes:
            log.info("Intentando screenshot de elemento...")
            for sel in [
                "mws-qr-code canvas",
                "mws-qr-code",
                "[data-e2e-qr-code]",
                "[data-e2e-qr-code] canvas",
                "canvas",
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        shot = await el.screenshot()
                        if shot and len(shot) > 2000:
                            log.info("QR capturado via screenshot elemento '%s'", sel)
                            qr_bytes = shot
                            break
                except Exception as e:
                    log.debug("Selector '%s' falló: %s", sel, e)
                    continue

        # ── Capa 3: screenshot completo (debug) ────────────────────────────
        if not qr_bytes:
            log.warning("Capas 1 y 2 fallaron, guardando screenshot completo para debug...")
            try:
                shot = await page.screenshot(full_page=False)
                # Guardar para diagnóstico
                debug_path = Path(SESSION_DIR) / "debug_qr.png"
                debug_path.write_bytes(shot)
                log.warning("Screenshot debug guardado en %s (%d bytes)", debug_path, len(shot))
                if shot and len(shot) > 5000:
                    qr_bytes = shot
            except Exception as e:
                log.error("Screenshot completo falló: %s", e)

    except Exception as e:
        log.error("capturar_qr error general: %s", e)
    finally:
        try: await page.close()
        except: pass

    return qr_bytes


# ══════════════════════════════════════════════════════════════
#  ENVÍO DE MENSAJES
# ══════════════════════════════════════════════════════════════

async def enviar_uno(page, numero: str) -> None:
    """
    Navega a nueva conversación, introduce el número y envía el mensaje.
    Lanza excepción si algo falla.
    """
    mensaje = state["message"]

    # 1. Navegación directa a nueva conversación
    await page.goto(URL_NUEVA, wait_until="domcontentloaded", timeout=TIMEOUT_NAV)
    await asyncio.sleep(0.8)
    await cerrar_overlays(page)

    if "authentication" in page.url:
        raise RuntimeError("Sesión caducada — vuelve a escanear el QR")

    # 2. Campo "Para:"
    campo_para = page.locator(SEL_PARA).first
    try:
        await campo_para.wait_for(state="visible", timeout=TIMEOUT_CAMPO)
    except PWTimeout:
        raise RuntimeError("No apareció el campo 'Para:'")

    await campo_para.click()
    await campo_para.fill(numero)
    await asyncio.sleep(1.3)
    await campo_para.press("Enter")
    await asyncio.sleep(0.6)

    # 3. Verificar chip del destinatario
    try:
        await page.locator(SEL_CHIP).first.wait_for(state="visible", timeout=5_000)
    except PWTimeout:
        raise ValueError(f"Número rechazado: {numero}")

    # 4. Campo de mensaje
    campo_msg = page.locator(SEL_MENSAJE).first
    try:
        await campo_msg.wait_for(state="visible", timeout=TIMEOUT_CAMPO)
    except PWTimeout:
        raise RuntimeError("No apareció el campo de mensaje")

    await campo_msg.click()
    await asyncio.sleep(0.3)
    await campo_msg.fill(mensaje)
    await asyncio.sleep(0.4)

    # 5. Enviar (Enter primero, botón como fallback)
    await campo_msg.press("Enter")

    enviado = False
    try:
        await page.wait_for_function(
            """() => {
                const ta = document.querySelector(
                    'mws-message-compose textarea, textarea[aria-label]'
                );
                return !ta || ta.value.trim() === '';
            }""",
            timeout=7_000,
        )
        enviado = True
    except Exception:
        pass

    if not enviado:
        try:
            btn = page.locator(SEL_ENVIAR).first
            if await btn.count() > 0 and await btn.is_enabled():
                await btn.click()
                await asyncio.sleep(1.0)
        except Exception:
            pass

    await asyncio.sleep(PAUSA_ENVIO)


async def tarea_envio(page, numero_raw: str) -> tuple[str, bool, str]:
    """
    Wrapper con reintentos para un número.
    Devuelve (numero_raw, exito, motivo_error).
    """
    numero = normalizar(numero_raw)
    for intento in range(1 + MAX_REINTENTOS):
        try:
            await enviar_uno(page, numero)
            return numero_raw, True, ""
        except ValueError as e:
            return numero_raw, False, str(e)          # No reintentar
        except Exception as e:
            if intento < MAX_REINTENTOS:
                await asyncio.sleep(2)
            else:
                return numero_raw, False, str(e)
    return numero_raw, False, "Reintentos agotados"


# ══════════════════════════════════════════════════════════════
#  ENVÍO MASIVO — 10 PÁGINAS EN PARALELO
# ══════════════════════════════════════════════════════════════

async def run_bulk_send(app: Application, chat: int) -> None:
    """
    Abre NUM_PAGINAS páginas en el servidor y procesa la lista
    en lotes de NUM_PAGINAS mensajes simultáneos.
    """
    context  = state["context"]
    contacts = state["contacts"]
    total    = len(contacts)

    if not context:
        await live(app, chat, "❌ *Navegador no disponible*", kb_main())
        return

    # ── Abrir las 10 páginas ──────────────────────────────────
    pages = []
    for _ in range(NUM_PAGINAS):
        p = await context.new_page()
        pages.append(p)
    state["pages"] = pages

    state["sent"]  = 0
    state["failed"] = 0
    state["total"] = total
    state["stop"]  = False
    state["phase"] = "sending"

    failed_nums: list[str] = []

    await live(app, chat,
        f"🚀 *Envío masivo iniciado*\n"
        f"📋 Contactos: *{total}*\n"
        f"⚡ Páginas paralelas: *{NUM_PAGINAS}*\n"
        f"✉️ Mensaje: _{state['message'][:60]}{'...' if len(state['message'])>60 else ''}_",
        kb_running(),
    )

    idx = 0
    while idx < total and not state["stop"]:
        lote_contactos = contacts[idx: idx + NUM_PAGINAS]
        lote_paginas   = pages[: len(lote_contactos)]

        tareas = [
            tarea_envio(page, numero_raw)
            for page, numero_raw in zip(lote_paginas, lote_contactos)
        ]
        resultados = await asyncio.gather(*tareas, return_exceptions=True)

        for res in resultados:
            if isinstance(res, Exception):
                state["failed"] += 1
                failed_nums.append("?")
            else:
                numero_raw, exito, motivo = res
                if exito:
                    state["sent"] += 1
                else:
                    state["failed"] += 1
                    failed_nums.append(numero_raw)

        idx += len(lote_contactos)

        done    = min(idx, total)
        pct     = done / total * 100
        filled  = int(pct / 100 * 10)
        bar     = "█" * filled + "░" * (10 - filled)

        try:
            await live(app, chat,
                f"📨 *Enviando...*\n\n"
                f"[{bar}] {done}/{total} ({pct:.0f}%)\n"
                f"✅ Enviados  : {state['sent']}\n"
                f"❌ Fallidos  : {state['failed']}",
                kb_running(),
            )
        except Exception:
            pass

    for p in pages:
        try: await p.close()
        except: pass
    state["pages"] = []
    state["phase"] = "connected"

    detenido = state["stop"]
    resumen = (
        f"{'⛔ *Envío detenido*' if detenido else '🏁 *¡Envío completado!*'}\n\n"
        f"✅ Enviados : *{state['sent']}*\n"
        f"❌ Fallidos : *{state['failed']}*\n"
        f"📊 Total    : *{total}*"
    )
    if failed_nums:
        muestra = failed_nums[:8]
        resumen += "\n\n⚠️ *Números fallidos (muestra):*\n" + "\n".join(muestra)
        if len(failed_nums) > 8:
            resumen += f"\n_...y {len(failed_nums)-8} más_"

    await live(app, chat, resumen, kb_done())


# ══════════════════════════════════════════════════════════════
#  TAREA BACKGROUND: CONECTAR GOOGLE MESSAGES
# ══════════════════════════════════════════════════════════════

async def do_connect(app: Application, chat: int) -> None:
    """Inicia el navegador, captura el QR y espera la autenticación."""
    state["phase"] = "qr"

    try:
        context = await init_browser()

        # ¿Ya hay sesión activa?
        if await ya_autenticado(context):
            state["phase"] = "connected"
            await live(app, chat,
                "✅ *Sesión ya activa*\n🟢 Google Messages vinculado y listo.",
                kb_main(),
            )
            return

        await live(app, chat,
            "🔄 *Cargando Google Messages...*\n⏳ Capturando código QR...",
            kb_cancel(),
        )

        qr_bytes = await capturar_qr(context)

        if not qr_bytes:
            await live(app, chat,
                "❌ *No se pudo obtener el QR*\n\n"
                "El navegador no pudo cargar la página.\n"
                "Pulsa *Reconectar* para reintentar.",
                kb_main(),
            )
            state["phase"] = "idle"
            return

        # Enviar foto del QR a Telegram
        state["live_msg_id"] = None
        await app.bot.send_photo(
            chat,
            io.BytesIO(qr_bytes),
            caption=(
                "📱 *Escanea este código QR*\n\n"
                "1️⃣  Abre *Google Messages* en tu móvil\n"
                "2️⃣  Menú ⋮ → *Mensajes para web*\n"
                "3️⃣  Pulsa *Escanear código QR*\n"
                "4️⃣  Apunta la cámara al código\n\n"
                "⏳ Esperando vinculación _(3 min max)_..."
            ),
            parse_mode="Markdown",
        )

        # Esperar a que el usuario escanee el QR
        ok = await esperar_autenticacion(context, timeout_s=180)

        if state["phase"] != "qr":
            return   # Cancelado por el usuario

        if ok:
            state["phase"] = "connected"
            m = await app.bot.send_message(
                chat,
                "✅ *¡Google Messages vinculado correctamente!*\n"
                "🟢 Listo para enviar mensajes masivos.",
                parse_mode="Markdown",
                reply_markup=kb_main(),
            )
            state["live_msg_id"] = m.message_id
        else:
            state["phase"] = "idle"
            await app.bot.send_message(
                chat,
                "⏰ *Tiempo agotado*\nEl QR expiró. Pulsa *Conectar* para generar uno nuevo.",
                parse_mode="Markdown",
                reply_markup=kb_main(),
            )

    except Exception as e:
        log.error("do_connect error: %s", e, exc_info=True)
        if state["phase"] == "qr":
            state["phase"] = "idle"
            await app.bot.send_message(
                chat,
                f"❌ *Error al conectar:* `{str(e)[:120]}`",
                parse_mode="Markdown",
                reply_markup=kb_main(),
            )


# ══════════════════════════════════════════════════════════════
#  TELEGRAM HANDLERS
# ══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        await update.message.reply_text("🚫 Acceso denegado")
        return

    chat = update.effective_chat.id
    state["chat"]        = chat
    state["live_msg_id"] = None

    fase = state["phase"]
    if fase == "connected":
        status = "🟢 Vinculado y listo"
    elif fase in ("wait_file", "wait_msg", "confirm"):
        status = "🟡 En proceso de configuración"
    elif fase == "sending":
        status = f"📨 Enviando ({state['sent']}/{state['total']})"
    elif fase == "qr":
        status = "🔄 Esperando escaneo QR"
    else:
        status = "🔴 Sin vincular"

    m = await update.message.reply_text(
        f"🤖 *Google Messages Bulk Sender*\n"
        f"📱 Estado: {status}\n\n"
        f"Selecciona una opción:",
        parse_mode="Markdown",
        reply_markup=kb_main(),
    )
    state["live_msg_id"] = m.message_id


async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    if not is_allowed(update):
        await q.message.reply_text("🚫 Acceso denegado")
        return

    chat = q.message.chat.id
    state["chat"]        = chat
    state["live_msg_id"] = q.message.message_id
    data = q.data

    if data == "main":
        fase = state["phase"]
        if fase == "connected":
            status = "🟢 Vinculado"
        elif fase == "sending":
            status = f"📨 Enviando ({state['sent']}/{state['total']})"
        elif fase == "qr":
            status = "🔄 Esperando QR"
        else:
            status = "🔴 Sin vincular"
        await live(ctx.application, chat,
            f"🤖 *Google Messages Bulk Sender*\n📱 Estado: {status}",
            kb_main(),
        )

    elif data == "connect":
        if state["phase"] == "sending":
            await live(ctx.application, chat,
                "⚠️ *Detén el envío antes de reconectar*", kb_running())
            return
        await live(ctx.application, chat, "🔄 *Iniciando navegador...*", kb_cancel())
        asyncio.create_task(do_connect(ctx.application, chat))

    elif data == "cancel":
        prev_phase = state["phase"]
        if prev_phase in ("qr", "wait_file", "wait_msg", "confirm"):
            if prev_phase == "qr":
                await cleanup_browser()
            state["phase"] = "idle" if prev_phase == "qr" else "connected"
            await live(ctx.application, chat, "❌ *Cancelado*", kb_main())
        else:
            await live(ctx.application, chat, "❌ *Nada que cancelar*", kb_main())

    elif data == "send":
        if state["phase"] != "connected":
            await live(ctx.application, chat,
                "❌ *Primero vincula Google Messages*\n"
                "Pulsa 📱 *Conectar Google Messages*",
                kb_main(),
            )
            return
        state["phase"] = "wait_file"
        await live(ctx.application, chat,
            "📄 *Paso 1 de 2 — Archivo de contactos*\n\n"
            "Envíame un archivo *.txt* con los números de teléfono\n"
            "_(un número por línea)_",
            kb_cancel(),
        )

    elif data == "confirm_send":
        if state["phase"] != "confirm":
            await live(ctx.application, chat,
                "⚠️ *No hay nada pendiente de confirmar*", kb_main())
            return
        asyncio.create_task(run_bulk_send(ctx.application, chat))

    elif data == "stop":
        if state["phase"] != "sending":
            await live(ctx.application, chat,
                "ℹ️ *No hay envíos en curso*", kb_main())
            return
        state["stop"] = True
        await live(ctx.application, chat, "⛔ *Deteniendo envío...*", kb_running())

    elif data == "status":
        if state["phase"] != "sending":
            await live(ctx.application, chat,
                "ℹ️ *No hay envíos en curso*", kb_main())
            return
        total  = state["total"]
        done   = state["sent"] + state["failed"]
        pct    = (done / total * 100) if total else 0
        filled = int(pct / 100 * 10)
        bar    = "█" * filled + "░" * (10 - filled)
        await live(ctx.application, chat,
            f"📊 *Estado del envío*\n\n"
            f"[{bar}] {done}/{total} ({pct:.0f}%)\n"
            f"✅ Enviados  : {state['sent']}\n"
            f"❌ Fallidos  : {state['failed']}\n"
            f"⚡ Paralelas : {NUM_PAGINAS} páginas",
            kb_running(),
        )

    elif data == "disconnect":
        if state["phase"] == "sending":
            await live(ctx.application, chat,
                "⚠️ *Detén el envío primero*", kb_running())
            return
        await cleanup_browser()
        try: shutil.rmtree(SESSION_DIR, ignore_errors=True)
        except: pass
        state["phase"] = "idle"
        await live(ctx.application, chat,
            "🔴 *Google Messages desvinculado*\n"
            "La sesión ha sido eliminada.",
            kb_main(),
        )


async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return

    chat  = update.effective_chat.id
    state["chat"] = chat
    phase = state["phase"]

    if phase == "wait_file":
        if update.message.document:
            doc = update.message.document
            if not doc.file_name.lower().endswith(".txt"):
                await ctx.bot.send_message(
                    chat, "❌ *Solo archivos .txt*", parse_mode="Markdown")
                return

            file    = await ctx.bot.get_file(doc.file_id)
            data_b  = await file.download_as_bytearray()
            texto   = data_b.decode("utf-8", errors="ignore")
            contacts = [ln.strip() for ln in texto.splitlines() if ln.strip()]

            if not contacts:
                await ctx.bot.send_message(
                    chat, "❌ *El archivo está vacío*", parse_mode="Markdown")
                return

            state["contacts"] = contacts
            state["phase"]    = "wait_msg"

            m = await ctx.bot.send_message(
                chat,
                f"✅ *{len(contacts)} contactos cargados*\n\n"
                f"📝 *Paso 2 de 2 — Mensaje*\n\n"
                f"Escribe el mensaje que quieres enviar:",
                parse_mode="Markdown",
                reply_markup=kb_cancel(),
            )
            state["live_msg_id"] = m.message_id
        else:
            await ctx.bot.send_message(
                chat,
                "📎 *Envíame el archivo .txt como documento*\n"
                "_(tócalo → Enviar como archivo)_",
                parse_mode="Markdown",
            )

    elif phase == "wait_msg":
        if update.message.text:
            mensaje = update.message.text.strip()
            if not mensaje:
                await ctx.bot.send_message(
                    chat, "❌ *El mensaje no puede estar vacío*", parse_mode="Markdown")
                return

            state["message"] = mensaje
            state["phase"]   = "confirm"
            total            = len(state["contacts"])
            prev_msg         = mensaje[:80] + ("..." if len(mensaje) > 80 else "")

            m = await ctx.bot.send_message(
                chat,
                f"📨 *Confirmar envío*\n\n"
                f"👥 Contactos : *{total}*\n"
                f"⚡ Paralelas  : *{NUM_PAGINAS} páginas*\n"
                f"✉️ Mensaje    :\n_{prev_msg}_\n\n"
                f"¿Proceder?",
                parse_mode="Markdown",
                reply_markup=kb_confirm(),
            )
            state["live_msg_id"] = m.message_id

    else:
        if update.message.text and not update.message.text.startswith("/"):
            await ctx.bot.send_message(
                chat,
                "🤖 Usa /start para ver el menú.",
                parse_mode="Markdown",
                reply_markup=kb_main(),
            )


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def main() -> None:
    print("═" * 60)
    print("   📨   Google Messages Bulk Sender — Telegram Bot v2")
    print("═" * 60)
    print(f"   🤖  Token  : {BOT_TOKEN[:10]}...")
    print(f"   👤  Usuario: @{ALLOWED_USER}")
    print(f"   ⚡  Páginas : {NUM_PAGINAS} paralelas")
    print("═" * 60)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(
        filters.ALL & ~filters.COMMAND, msg_handler
    ))

    print("✅  Bot iniciado. Esperando mensajes...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
