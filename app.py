"""
🎵 BTS Ticket Monitor - Render Cloud Deployment
================================================
Flask web server + APScheduler background monitor.
Revisa Ticketmaster Colombia cada 60s y alerta por Telegram.
"""

import os
import logging
import threading

import requests as http_requests
from flask import Flask, jsonify, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

from monitor import run_check, get_state, MAIN_URL, ALL_URLS
from notifier import send_telegram, is_configured

# ============================================================
# Configuración
# ============================================================
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
PORT = int(os.getenv("PORT", "10000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")  # Render lo provee automáticamente

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================================
# Flask App
# ============================================================
app = Flask(__name__)

# HTML del dashboard
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BTS Ticket Monitor 💜</title>
    <meta name="description" content="Monitor de boletas BTS World Tour ARIRANG - Ticketmaster Colombia">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0f0f1a;
            --card: #1a1a2e;
            --accent: #9b59b6;
            --accent2: #8e44ad;
            --green: #27ae60;
            --red: #e74c3c;
            --yellow: #f39c12;
            --text: #ecf0f1;
            --text-dim: #7f8c8d;
            --border: rgba(155, 89, 182, 0.2);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 2rem 1rem;
        }
        .container { max-width: 700px; width: 100%; }
        .header {
            text-align: center;
            margin-bottom: 2rem;
            animation: fadeIn 0.8s ease;
        }
        .header h1 {
            font-size: 2.2rem;
            font-weight: 900;
            background: linear-gradient(135deg, #9b59b6, #e74c3c, #f39c12);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 0.3rem;
        }
        .header .subtitle {
            color: var(--text-dim);
            font-size: 0.95rem;
        }
        .status-card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 1.8rem;
            margin-bottom: 1.2rem;
            backdrop-filter: blur(10px);
            animation: slideUp 0.5s ease;
        }
        .status-card h2 {
            font-size: 1rem;
            font-weight: 600;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 1.5px;
            margin-bottom: 1rem;
        }
        .status-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.6rem 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .status-row:last-child { border-bottom: none; }
        .status-row .label { color: var(--text-dim); font-size: 0.9rem; }
        .status-row .value { font-weight: 600; font-size: 0.95rem; }
        .badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 700;
        }
        .badge-red { background: rgba(231,76,60,0.2); color: var(--red); }
        .badge-green { background: rgba(39,174,96,0.2); color: var(--green); }
        .badge-yellow { background: rgba(243,156,18,0.2); color: var(--yellow); }
        .badge-purple { background: rgba(155,89,182,0.2); color: var(--accent); }
        .pulse {
            display: inline-block;
            width: 10px; height: 10px;
            border-radius: 50%;
            background: var(--green);
            margin-right: 6px;
            animation: pulse 2s ease infinite;
        }
        .big-status {
            text-align: center;
            padding: 2rem;
            font-size: 1.4rem;
            font-weight: 700;
        }
        .footer {
            text-align: center;
            margin-top: 2rem;
            color: var(--text-dim);
            font-size: 0.8rem;
        }
        .footer a { color: var(--accent); text-decoration: none; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(1.3); } }
        .refresh-note {
            text-align: center;
            color: var(--text-dim);
            font-size: 0.8rem;
            margin-top: 1rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎵 BTS Ticket Monitor</h1>
            <p class="subtitle">WORLD TOUR ARIRANG 2026 — Bogotá, Colombia</p>
        </div>

        <div class="status-card">
            <h2><span class="pulse"></span> Estado del Monitor</h2>
            <div class="status-row">
                <span class="label">Estado</span>
                <span class="value">
                    {% if state.last_status == 'available' %}
                        <span class="badge badge-green">✅ ¡DISPONIBLE!</span>
                    {% elif state.last_status == 'sold_out' %}
                        <span class="badge badge-red">🔴 Agotado</span>
                    {% elif state.last_status == 'error' %}
                        <span class="badge badge-yellow">⚠️ Error</span>
                    {% else %}
                        <span class="badge badge-purple">🔄 Iniciando...</span>
                    {% endif %}
                </span>
            </div>
            <div class="status-row">
                <span class="label">Checks realizados</span>
                <span class="value">{{ state.check_count }}</span>
            </div>
            <div class="status-row">
                <span class="label">"AGOTADO" en página</span>
                <span class="value">{{ state.previous_agotado_count if state.previous_agotado_count is not none else '—' }}</span>
            </div>
            <div class="status-row">
                <span class="label">Errores consecutivos</span>
                <span class="value">{{ state.consecutive_errors }}</span>
            </div>
            <div class="status-row">
                <span class="label">Intervalo</span>
                <span class="value">cada {{ interval }}s</span>
            </div>
            <div class="status-row">
                <span class="label">Activo desde</span>
                <span class="value">{{ state.started_at[:19] }}</span>
            </div>
            <div class="status-row">
                <span class="label">Telegram</span>
                <span class="value">
                    {% if telegram_ok %}
                        <span class="badge badge-green">✅ Conectado</span>
                    {% else %}
                        <span class="badge badge-red">❌ No configurado</span>
                    {% endif %}
                </span>
            </div>
        </div>

        <div class="status-card">
            <h2>🔗 Páginas Monitoreadas ({{ pages|length }})</h2>
            {% for page in pages %}
            <div class="status-row">
                <span class="label">{{ page.name }}</span>
                <span class="value">
                    {% set ps = state.pages.get(page.id, {}) %}
                    {% if ps.get('last_status') == 'available' %}
                        <span class="badge badge-green">✅ DISPONIBLE</span>
                    {% elif ps.get('last_status') == 'sold_out' %}
                        <span class="badge badge-red">🔴 {{ ps.get('agotado_count', '?') }}x Agotado</span>
                    {% else %}
                        <span class="badge badge-purple">⏳ Pendiente</span>
                    {% endif %}
                </span>
            </div>
            {% endfor %}
            <div class="status-row" style="margin-top: 0.5rem;">
                <span class="label">Evento</span>
                <span class="value">BTS ARIRANG — El Campín</span>
            </div>
            <div class="status-row">
                <span class="label">Fechas</span>
                <span class="value">Oct 2 y 3, 2026</span>
            </div>
        </div>

        <p class="refresh-note">
            Esta página se actualiza al recargar. El monitor corre automáticamente en segundo plano.
        </p>

        <div class="footer">
            <p>Hecho con 💜 para ARMY — Powered by <a href="https://render.com">Render</a></p>
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def dashboard():
    """Dashboard visual del monitor."""
    state = get_state()
    return render_template_string(
        DASHBOARD_HTML,
        state=state,
        interval=CHECK_INTERVAL,
        telegram_ok=is_configured(),
        url=MAIN_URL,
        pages=ALL_URLS,
    )


@app.route("/health")
@app.route("/ping")
def health():
    """Endpoint de health-check para mantener el servicio activo."""
    state = get_state()
    return jsonify({
        "status": "running",
        "checks": state["check_count"],
        "last_status": state["last_status"],
        "errors": state["consecutive_errors"],
    })


@app.route("/api/status")
def api_status():
    """API JSON con el estado completo."""
    return jsonify(get_state())


@app.route("/api/force-check", methods=["POST"])
def force_check():
    """Fuerza un chequeo inmediato."""
    run_check()
    return jsonify({"message": "Check ejecutado", "state": get_state()})


# ============================================================
# Self-ping para mantener vivo en Render Free Tier
# ============================================================
def self_ping():
    """Se hace ping a sí mismo para evitar el spin-down de Render."""
    if RENDER_URL:
        try:
            http_requests.get(f"{RENDER_URL}/ping", timeout=10)
            logger.debug("🏓 Self-ping OK")
        except Exception:
            pass


# ============================================================
# Inicialización
# ============================================================
# Declarar el scheduler de forma global para evitar que Python lo borre (Garbage Collection)
scheduler = BackgroundScheduler(daemon=True)

def start_scheduler():
    """Inicia el scheduler de tareas en background."""
    # Tarea principal: monitorear Ticketmaster
    scheduler.add_job(
        run_check,
        "interval",
        seconds=CHECK_INTERVAL,
        id="ticket_check",
        name="Ticketmaster BTS Check",
        max_instances=1,
        misfire_grace_time=30,
    )

    # Self-ping cada 10 minutos (para evitar spin-down en Render free)
    if RENDER_URL:
        scheduler.add_job(
            self_ping,
            "interval",
            minutes=10,
            id="self_ping",
            name="Self Ping Keep-Alive",
        )

    scheduler.start()
    logger.info("⏰ Scheduler iniciado — Intervalo: %ds", CHECK_INTERVAL)


# Iniciar scheduler al cargar el módulo (gunicorn lo carga una vez)
_scheduler_started = False


def init_app():
    """Inicializa la aplicación (una sola vez)."""
    global _scheduler_started
    if not _scheduler_started:
        _scheduler_started = True
        logger.info("=" * 55)
        logger.info("🎵  BTS WORLD TOUR ARIRANG — Ticket Monitor")
        logger.info("📍  Ticketmaster Colombia")
        logger.info("📅  Oct 2-3, 2026 — Estadio El Campín, Bogotá")
        logger.info("=" * 55)

        if is_configured():
            logger.info("✅ Telegram configurado")
            send_telegram(
                "🤖 *Monitor BTS iniciado en la nube*\n\n"
                f"Revisaré {len(ALL_URLS)} páginas cada {CHECK_INTERVAL} segundos.\n"
                "(Página principal + 4 eventos individuales)\n"
                "Te avisaré cuando detecte cambios. 💜\n\n"
                f"📊 Dashboard: {RENDER_URL or 'N/A'}"
            )
        else:
            logger.warning("⚠️ Telegram NO configurado — configura las variables de entorno")

        start_scheduler()

        # Primer chequeo inmediato
        logger.info("🔍 Ejecutando primer chequeo...")
        run_check()


# Iniciar al recibir la primera petición (para evitar problemas de hilos con gunicorn)
@app.before_request
def initialize_on_first_request():
    init_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
