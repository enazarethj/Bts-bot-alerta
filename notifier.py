"""
Módulo de notificaciones por Telegram.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def is_configured() -> bool:
    """Verifica si Telegram está configurado."""
    return bool(TELEGRAM_BOT_TOKEN) and bool(TELEGRAM_CHAT_ID)


def send_telegram(message: str, parse_mode: str = "Markdown") -> bool:
    """Envía un mensaje por Telegram."""
    if not is_configured():
        logger.warning("⚠️ Telegram no configurado. Mensaje: %s", message[:100])
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("✅ Telegram enviado OK")
            return True
        else:
            logger.error("❌ Telegram error %s: %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        logger.error("❌ Telegram excepción: %s", e)
        return False
