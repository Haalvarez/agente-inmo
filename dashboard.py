import logging
import os
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify

from database import get_all, get_stats

logger = logging.getLogger(__name__)

app = Flask(__name__)

_next_run: datetime | None = None


def set_next_run(dt: datetime):
    global _next_run
    _next_run = dt


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
        filters=filters,
        zonas=[
            "tigre", "nordelta", "delta", "rincon-de-milberg",
            "general-pacheco", "don-torcuato", "benavidez",
            "san-isidro", "belgrano", "palermo", "caballito", "villa-urquiza",
        ],
        tipos=["casas", "terrenos", "ph", "departamentos"],
    )


@app.route("/api/stats")
def api_stats():
    stats = get_stats()
    return jsonify(stats)


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
