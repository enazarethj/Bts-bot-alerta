"""
Módulo de monitoreo de Ticketmaster Colombia para BTS.
Revisa la página principal Y cada página individual de evento
para detectar cambios en disponibilidad.
"""

import os
import json
import hashlib
import logging
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

from notifier import send_telegram

logger = logging.getLogger(__name__)

# ============================================================
# Configuración de URLs
# ============================================================

# La URL principal que lista todos los eventos
MAIN_URL = os.getenv(
    "TICKETMASTER_URL",
    "https://www.ticketmaster.co/event/bts-world-tour-2026",
)

# URLs individuales de cada evento (verificadas del sitio real)
ALL_URLS = [
    {
        "id": "main",
        "name": "📋 Página Principal BTS",
        "url": MAIN_URL,
    },
    {
        "id": "oct2-army",
        "name": "🗓️ Vie Oct 2 - Preventa ARMY",
        "url": "https://www.ticketmaster.co/event/bts-world-tour-army-membership-viernes-2-octubre",
    },
    {
        "id": "oct2-general",
        "name": "🗓️ Vie Oct 2 - Venta General",
        "url": "https://www.ticketmaster.co/event/bts-world-tour-venta-general-viernes-2-octubre",
    },
    {
        "id": "oct3-army",
        "name": "🗓️ Sáb Oct 3 - Preventa ARMY",
        "url": "https://www.ticketmaster.co/event/bts-world-tour-army-membership-sabado-3-octubre",
    },
    {
        "id": "oct3-general",
        "name": "🗓️ Sáb Oct 3 - Venta General",
        "url": "https://www.ticketmaster.co/event/bts-world-tour-venta-general-sabado-3-octubre",
    },
]

# Intervalo de re-alerta en minutos
RE_ALERT_MINUTES = int(os.getenv("RE_ALERT_MINUTES", "10"))

# Headers para simular navegador
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Estado persistente (en memoria para Render - ephemeral filesystem)
_state = {
    "last_alerts": {},
    "pages": {},  # estado por cada URL: {id: {agotado_count, content_hash, last_status}}
    "check_count": 0,
    "consecutive_errors": 0,
    "last_status": "unknown",
    "started_at": datetime.now().isoformat(),
}


def get_state() -> dict:
    """Retorna el estado actual del monitor."""
    return _state.copy()


def _should_alert(key: str) -> bool:
    """Verifica si ya pasó el cooldown para re-alertar."""
    last = _state["last_alerts"].get(key)
    if not last:
        return True
    try:
        elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 60
        return elapsed >= RE_ALERT_MINUTES
    except Exception:
        return True


def _fetch_page(url: str) -> dict:
    """
    Hace fetch de la página de Ticketmaster y analiza disponibilidad.
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        resp = session.get(url, timeout=30, allow_redirects=True)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        page_text = soup.get_text(separator=" ", strip=True)
        page_lower = page_text.lower()

        result = {
            "ok": True,
            "status": "sold_out",
            "agotado_count": page_lower.count("agotado"),
            "final_url": resp.url,
            "details": [],
            "page_snippet": page_text[:1000],
        }

        # ----- Buscar botones/links de compra -----
        buy_keywords = [
            "comprar", "compra ya", "añadir", "agregar",
            "buy", "get tickets", "add to cart", "seleccionar",
        ]
        for elem in soup.find_all(["button", "a", "input"]):
            elem_text = elem.get_text(strip=True).lower()
            href = (elem.get("href") or "").lower()
            for kw in buy_keywords:
                if kw in elem_text or kw in href:
                    result["status"] = "available"
                    result["details"].append(f"Botón/link: '{elem_text[:80]}'")
                    break

        # ----- Buscar links de checkout/purchase -----
        for link in soup.find_all("a", href=True):
            href = link.get("href", "").lower()
            if any(k in href for k in ["checkout", "cart", "purchase", "comprar"]):
                result["status"] = "available"
                result["details"].append(f"Link compra: {link.get('href')}")

        # ----- Buscar selectores de zona/localidad -----
        zone_keywords = [
            "vip", "general", "sur", "norte", "oriental",
            "occidental", "platea", "zona", "localidad",
        ]
        for sel in soup.find_all(["select", "option"]):
            sel_text = sel.get_text(strip=True).lower()
            if any(z in sel_text for z in zone_keywords):
                result["status"] = "available"
                result["details"].append(f"Selector zona: '{sel_text[:80]}'")

        # ----- Generar un hash del contenido relevante -----
        relevant = "".join(
            e.get_text(strip=True)
            for e in soup.find_all(["button", "a"])
            if "agotado" in e.get_text(strip=True).lower()
            or "comprar" in e.get_text(strip=True).lower()
            or "bts" in e.get_text(strip=True).lower()
        )
        result["content_hash"] = hashlib.md5(relevant.encode()).hexdigest()

        return result

    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        return {"ok": False, "error": f"HTTP {code}", "status": "error"}
    except Exception as e:
        return {"ok": False, "error": str(e), "status": "error"}


def _check_single_page(page_info: dict, now_str: str):
    """
    Revisa una sola página y genera alertas si hay cambios.
    """
    page_id = page_info["id"]
    page_name = page_info["name"]
    page_url = page_info["url"]

    logger.info("  📄 Revisando: %s", page_name)

    result = _fetch_page(page_url)

    if not result.get("ok"):
        err = result.get("error", "Unknown")
        logger.warning("    ⚠️ Error en %s: %s", page_name, err)
        return False

    # Inicializar estado de esta página si no existe
    if page_id not in _state["pages"]:
        _state["pages"][page_id] = {
            "agotado_count": None,
            "content_hash": None,
            "last_status": "unknown",
        }

    page_state = _state["pages"][page_id]
    agotado = result["agotado_count"]
    status = result["status"]

    logger.info(
        "    Estado: %s | AGOTADO: %d | Detalles: %d",
        status, agotado, len(result.get("details", [])),
    )

    # ============================================================
    # ¿HAY BOLETAS DISPONIBLES EN ESTA PÁGINA?
    # ============================================================
    if status == "available":
        page_state["last_status"] = "available"
        alert_key = f"{page_id}_available"
        if _should_alert(alert_key):
            details = "\n".join(f"  • {d}" for d in result["details"][:5])
            msg = (
                "🚨🚨🚨 *¡¡ALERTA BTS TICKETS!!* 🚨🚨🚨\n\n"
                f"🎵 *{page_name}*\n"
                f"📅 {now_str}\n\n"
                "✅ *¡¡POSIBLEMENTE HAY BOLETAS DISPONIBLES!!*\n\n"
                f"📋 Detalles:\n{details}\n\n"
                f"🔗 [¡IR A COMPRAR AHORA!]({page_url})\n\n"
                "⚡ *¡CORRE ANTES DE QUE SE AGOTEN!* ⚡💜"
            )
            send_telegram(msg)
            _state["last_alerts"][alert_key] = datetime.now().isoformat()
    else:
        page_state["last_status"] = "sold_out"

    # ============================================================
    # ¿CAMBIÓ EL CONTEO DE AGOTADO EN ESTA PÁGINA?
    # ============================================================
    prev = page_state["agotado_count"]
    if prev is not None and agotado != prev:
        alert_key = f"{page_id}_agotado_change"
        if _should_alert(alert_key):
            direction = "📉 MENOS" if agotado < prev else "📈 MÁS"
            emoji = "🟢" if agotado < prev else "🔵"
            extra = ""
            if agotado < prev:
                extra = "\n\n🎫 *¡Puede que hayan liberado entradas!*"

            msg = (
                f"{emoji} *Cambio detectado*\n\n"
                f"🎵 *{page_name}*\n"
                f"📅 {now_str}\n"
                f"📊 'AGOTADO' antes: {prev} → ahora: {agotado}\n"
                f"{direction} veces agotado{extra}\n\n"
                f"🔗 [Ver en Ticketmaster]({page_url})\n\n"
                "👀 *¡Revisa rápido!*"
            )
            send_telegram(msg)
            _state["last_alerts"][alert_key] = datetime.now().isoformat()

    page_state["agotado_count"] = agotado

    # ============================================================
    # ¿CAMBIÓ EL CONTENIDO DE ESTA PÁGINA?
    # ============================================================
    new_hash = result.get("content_hash")
    old_hash = page_state["content_hash"]
    if old_hash is not None and new_hash != old_hash:
        alert_key = f"{page_id}_content_change"
        if _should_alert(alert_key):
            msg = (
                "🔔 *Cambio de contenido detectado*\n\n"
                f"🎵 *{page_name}*\n"
                f"📅 {now_str}\n"
                "La página cambió su contenido.\n\n"
                f"🔗 [Revisar ahora]({page_url})"
            )
            send_telegram(msg)
            _state["last_alerts"][alert_key] = datetime.now().isoformat()

    page_state["content_hash"] = new_hash

    return True


def run_check():
    """
    Ejecuta un ciclo de verificación de TODAS las páginas.
    Llamada por el scheduler cada X segundos.
    """
    _state["check_count"] += 1
    check_num = _state["check_count"]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info("━" * 50)
    logger.info("🔍 Check #%d — %s — Revisando %d páginas", check_num, now_str, len(ALL_URLS))

    errors = 0
    for page_info in ALL_URLS:
        success = _check_single_page(page_info, now_str)
        if not success:
            errors += 1
        # Pequeña pausa entre páginas para no saturar
        time.sleep(2)

    if errors == len(ALL_URLS):
        _state["consecutive_errors"] += 1
        _state["last_status"] = "error"
        if _state["consecutive_errors"] == 5:
            send_telegram(
                "⚠️ *Monitor BTS - Advertencia*\n\n"
                f"Van {_state['consecutive_errors']} rondas con todas las páginas fallando.\n\n"
                "Puede estar bloqueado temporalmente."
            )
    else:
        _state["consecutive_errors"] = 0
        # Determinar estado general
        any_available = any(
            _state["pages"].get(p["id"], {}).get("last_status") == "available"
            for p in ALL_URLS
        )
        _state["last_status"] = "available" if any_available else "sold_out"

    logger.info("  ✅ Check #%d completo — %d errores de %d páginas", check_num, errors, len(ALL_URLS))
