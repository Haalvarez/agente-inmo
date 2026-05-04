import logging
import os
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

from database import init_db, upsert_propiedad
from scraper import run_scraping
from analyzer import analizar_lote
from notifier import enviar_alertas, enviar_mensaje
from dashboard import run_dashboard, set_next_run


CICLO_HORAS = 6


def pipeline():
    logger.info("═══ Iniciando ciclo de scraping ═══")

    try:
        enviar_mensaje("🔄 Ciclo iniciado — buscando propiedades...")
    except Exception:
        pass

    # ── Scraping ──
    try:
        props = run_scraping()
        logger.info("Scraping: %d propiedades obtenidas", len(props))
    except Exception as e:
        logger.error("Fallo en scraping: %s", e)
        try:
            enviar_mensaje(f"❌ Error en scraping: {e}")
        except Exception:
            pass
        return

    if not props:
        logger.warning("Sin propiedades para analizar")
        try:
            enviar_mensaje("⚠️ Ciclo completado — sin propiedades nuevas")
        except Exception:
            pass
        return

    # ── Análisis con Claude ──
    try:
        props_analizadas = analizar_lote(props)
        logger.info("Análisis completo: %d propiedades", len(props_analizadas))
    except Exception as e:
        logger.error("Fallo en análisis: %s", e)
        props_analizadas = props

    # ── Persistencia ──
    nuevas = 0
    for prop in props_analizadas:
        try:
            _, es_nueva = upsert_propiedad(prop)
            if es_nueva:
                nuevas += 1
        except Exception as e:
            logger.error("Error guardando prop %s: %s", prop.get("url"), e)

    logger.info("Guardadas: %d nuevas / %d actualizadas", nuevas, len(props_analizadas) - nuevas)

    # ── Alertas Telegram ──
    enviadas = 0
    try:
        enviadas = enviar_alertas(max_alertas=5)
        logger.info("Alertas Telegram: %d enviadas", enviadas)
    except Exception as e:
        logger.error("Fallo en notificaciones: %s", e)

    # ── Resumen de ciclo ──
    try:
        resumen = (
            f"✅ Ciclo completado\n"
            f"  📦 Analizadas: {len(props_analizadas)}\n"
            f"  🆕 Nuevas en DB: {nuevas}\n"
            f"  🔔 Alertas enviadas: {enviadas}"
        )
        enviar_mensaje(resumen)
    except Exception:
        pass

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

    scheduler.start()
    logger.info("Scheduler iniciado — ciclo cada %dhs", CICLO_HORAS)

    # Actualizar next_run en el dashboard
    try:
        next_dt = datetime.now() + timedelta(hours=CICLO_HORAS)
        set_next_run(next_dt)
    except Exception:
        pass

    # Notificar arranque (después de que el scheduler ya lanzó el primer ciclo)
    try:
        enviar_mensaje("🚀 Agente Inmobiliario iniciado — primer ciclo arrancando ahora...")
    except Exception as e:
        logger.warning("No se pudo enviar mensaje de arranque: %s", e)

    port = int(os.environ.get("PORT", 5000))
    run_dashboard(port=port)


if __name__ == "__main__":
    main()
