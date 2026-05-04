import logging
import os

import requests

from database import get_pendientes_notificar, marcar_notificado, get_media_movil

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

SCORE_EMOJIS = {
    10: "🔥🔥🔥",
    9: "🔥🔥",
    8: "🔥",
    7: "⭐",
}

TIPO_EMOJIS = {
    "casas": "🏠",
    "terrenos": "🏗️",
    "ph": "🏢",
    "departamentos": "🏬",
}


def _formato_mensaje(prop: dict) -> str:
    score = prop.get("score", 0)
    emoji_score = SCORE_EMOJIS.get(score, "📍")
    emoji_tipo = TIPO_EMOJIS.get(prop.get("tipo", ""), "🏠")

    zona = prop.get("zona", "N/A")
    media_zona = get_media_movil(zona)
    precio_m2 = prop.get("precio_m2")

    delta_str = ""
    if precio_m2 and media_zona:
        delta = ((precio_m2 - media_zona) / media_zona) * 100
        signo = "+" if delta >= 0 else ""
        delta_str = f"  📊 Delta vs zona: {signo}{delta:.1f}%\n"

    precio = prop.get("precio_usd")
    precio_str = f"USD {precio:,.0f}" if precio else "N/A"
    m2 = prop.get("m2")
    m2_str = f"{m2:.0f} m²" if m2 else "N/A"
    pm2_str = f"USD {precio_m2:,.0f}/m²" if precio_m2 else "N/A"

    titulo = (prop.get("titulo") or "Sin título")[:80]
    resumen = prop.get("resumen", "")
    url = prop.get("url", "")

    return (
        f"{emoji_score} *SCORE {score}/10* {emoji_tipo} {prop.get('tipo','').upper()}\n"
        f"📍 *{zona.upper()}*\n"
        f"  💰 Precio: {precio_str}\n"
        f"  📐 Superficie: {m2_str}\n"
        f"  🔑 USD/m²: {pm2_str}\n"
        f"{delta_str}"
        f"  📝 {titulo}\n\n"
        f"🤖 _{resumen}_\n\n"
        f"🔗 {url}"
    )


def _send_telegram(token: str, chat_id: str, text: str) -> bool:
    try:
        resp = requests.post(
            TELEGRAM_API.format(token=token),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Telegram OK: %s", resp.json().get("ok"))
        return True
    except Exception as e:
        logger.error("Error Telegram: %s", e)
        return False


def enviar_mensaje(texto: str) -> bool:
    """Envía un mensaje de texto simple al bot de Telegram."""
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "6702422377")
    if not token:
        logger.warning("TELEGRAM_TOKEN no configurado, no se puede enviar mensaje")
        return False
    return _send_telegram(token, chat_id, texto)


def enviar_alertas(max_alertas: int = 5) -> int:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "6702422377")

    if not token:
        logger.warning("TELEGRAM_TOKEN no configurado, saltando notificaciones")
        return 0

    pendientes = get_pendientes_notificar(min_score=7, limit=max_alertas)
    enviados = 0

    for prop in pendientes:
        mensaje = _formato_mensaje(prop)
        ok = _send_telegram(token, chat_id, mensaje)
        if ok:
            marcar_notificado(prop["id"])
            enviados += 1
            logger.info("Alerta enviada para prop id=%s score=%s", prop["id"], prop["score"])

    logger.info("Alertas enviadas: %d/%d", enviados, len(pendientes))
    return enviados
