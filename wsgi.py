"""
Punto de entrada para gunicorn.
Inicia DB + scheduler antes de que gunicorn empiece a servir requests.
"""
import logging
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from database import init_db
from dashboard import app, set_next_run, set_last_run_stats  # app es el objeto Flask  # noqa: F401

_scheduler_started = False


def _start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    from apscheduler.schedulers.background import BackgroundScheduler
    from main import pipeline, CICLO_HORAS
    from notifier import enviar_mensaje

    init_db()

    scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")
    scheduler.add_job(
        pipeline,
        trigger="interval",
        hours=CICLO_HORAS,
        id="pipeline",
        next_run_time=datetime.now(),
    )
    scheduler.start()
    logger.info("Scheduler iniciado — ciclo cada %dhs", CICLO_HORAS)

    try:
        set_next_run(datetime.now() + timedelta(hours=CICLO_HORAS))
    except Exception:
        pass

    try:
        enviar_mensaje("🚀 Agente Inmobiliario iniciado — primer ciclo arrancando ahora...")
    except Exception as e:
        logger.warning("No se pudo enviar mensaje de arranque: %s", e)


# gunicorn importa este módulo una vez con --preload, lo que ejecuta el bloque
# de nivel de módulo antes de hacer fork de workers.
_start_scheduler()
