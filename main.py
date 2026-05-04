import logging
import os
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from database import init_db
from scraper import run_scraping
from analyzer import analizar_lote
from notifier import enviar_alertas
from dashboard import run_dashboard, set_next_run


CICLO_HORAS = 6


def pipeline():
    logger.info("═══ Iniciando ciclo de scraping ═══")
    try:
        props = run_scraping()
        logger.info("Scraping: %d propiedades obtenidas", len(props))
    except Exception as e:
        logger.error("Fallo en scraping: %s", e)
        return

    if not props:
        logger.warning("Sin propiedades para analizar")
        return

    try:
        props_analizadas = analizar_lote(props)
        logger.info("Análisis completo: %d propiedades", len(props_analizadas))
    except Exception as e:
        logger.error("Fallo en análisis: %s", e)
        props_analizadas = props

    # persistir en DB
    from database import upsert_propiedad
    nuevas = 0
    for prop in props_analizadas:
        try:
            _, es_nueva = upsert_propiedad(prop)
            if es_nueva:
                nuevas += 1
        except Exception as e:
            logger.error("Error guardando prop %s: %s", prop.get("url"), e)

    logger.info("Guardadas: %d nuevas / %d actualizadas", nuevas, len(props_analizadas) - nuevas)

    try:
        enviadas = enviar_alertas(max_alertas=5)
        logger.info("Alertas Telegram: %d enviadas", enviadas)
    except Exception as e:
        logger.error("Fallo en notificaciones: %s", e)

    logger.info("═══ Ciclo completado ═══")


def main():
    init_db()

    scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")

    scheduler.add_job(
        pipeline,
        trigger="interval",
        hours=CICLO_HORAS,
        id="pipeline",
        next_run_time=datetime.now(),  # primer ciclo inmediato
    )

    def update_next_run():
        job = scheduler.get_job("pipeline")
        if job and job.next_run_time:
            set_next_run(job.next_run_time.replace(tzinfo=None))

    scheduler.add_listener(lambda e: update_next_run(), mask=0x1)  # EVENT_SCHEDULER_STARTED

    scheduler.start()
    logger.info("Scheduler iniciado — ciclo cada %dhs", CICLO_HORAS)

    # actualizar next_run inicial
    try:
        next_dt = datetime.now() + timedelta(hours=CICLO_HORAS)
        set_next_run(next_dt)
    except Exception:
        pass

    port = int(os.environ.get("PORT", 5000))
    run_dashboard(port=port)


if __name__ == "__main__":
    main()
