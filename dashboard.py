import logging
import os
import re
import time
from datetime import datetime, timedelta

import requests
from flask import Flask, render_template, request, jsonify

from database import get_all, get_stats

logger = logging.getLogger(__name__)

app = Flask(__name__)

_next_run: datetime | None = None
_last_run_stats: dict = {}


def set_next_run(dt: datetime):
    global _next_run
    _next_run = dt


def set_last_run_stats(stats: dict):
    global _last_run_stats
    _last_run_stats = stats


@app.route("/")
def index():
    filters = {}
    zona = request.args.get("zona", "").strip()
    tipo = request.args.get("tipo", "").strip()
    min_score_str = request.args.get("min_score", "").strip()

    if zona:
        filters["zona"] = zona
    if tipo:
        filters["tipo"] = tipo
    if min_score_str:
        try:
            filters["min_score"] = int(min_score_str)
        except ValueError:
            pass

    propiedades = get_all(filters)
    stats = get_stats()

    next_run_str = "N/A"
    if _next_run:
        next_run_str = _next_run.strftime("%d/%m/%Y %H:%M")

    return render_template(
        "index.html",
        propiedades=propiedades,
        stats=stats,
        next_run=next_run_str,
        last_run=_last_run_stats,
        filters=filters,
        zonas=[
            "tigre", "nordelta", "delta", "rincon-de-milberg",
            "general-pacheco", "don-torcuato", "benavidez",
            "san-isidro", "belgrano", "palermo", "caballito", "villa-urquiza",
        ],
        tipos=["casas", "terrenos", "ph", "departamentos"],
    )


@app.route("/status")
def status():
    stats = get_stats()
    next_run_str = _next_run.isoformat() if _next_run else None
    return jsonify({
        "db": stats,
        "next_run": next_run_str,
        "last_run": _last_run_stats,
    })


@app.route("/diagnostico")
def diagnostico():
    urls_a_testear = [
        "https://inmuebles.mercadolibre.com.ar/departamentos/venta/bs-as-gba-norte/",
        "https://inmuebles.mercadolibre.com.ar/casas/venta/bs-as-gba-norte/",
        "https://www.zonaprop.com.ar/departamentos-venta-zona-norte.html",
        "https://www.zonaprop.com.ar/casas-venta-zona-norte.html",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        ip_resp = requests.get("https://api.ipify.org?format=json", timeout=5)
        ip_origen = ip_resp.json().get("ip", "desconocido")
    except Exception:
        ip_origen = "desconocido"

    resultados = []
    for url in urls_a_testear:
        resultado = {"url": url, "status_code": None, "content_length": 0,
                     "elapsed_ms": 0, "has_listings": False, "title": None, "error": None}
        try:
            t0 = time.monotonic()
            resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            elapsed_ms = int((time.monotonic() - t0) * 1000)

            html = resp.text
            resultado["status_code"] = resp.status_code
            resultado["content_length"] = len(resp.content)
            resultado["elapsed_ms"] = elapsed_ms

            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            resultado["title"] = title_match.group(1).strip() if title_match else None

            has_price = "$" in html or "USD" in html
            has_prop_term = any(t in html for t in ["dormitorio", "ambientes", "m²", "m2"])
            resultado["has_listings"] = has_price and has_prop_term

        except Exception as exc:
            resultado["error"] = str(exc)

        resultados.append(resultado)

    return jsonify({
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "ip_origen_externa": ip_origen,
        "resultados": resultados,
    })


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


@app.route("/api/propiedades")
def api_propiedades():
    filters = {}
    zona = request.args.get("zona", "").strip()
    tipo = request.args.get("tipo", "").strip()
    min_score = request.args.get("min_score", "").strip()
    if zona:
        filters["zona"] = zona
    if tipo:
        filters["tipo"] = tipo
    if min_score:
        try:
            filters["min_score"] = int(min_score)
        except ValueError:
            pass
    return jsonify(get_all(filters))


def run_dashboard(port: int = 5000):
    port = int(os.environ.get("PORT", port))
    logger.info("Dashboard iniciando en puerto %d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
