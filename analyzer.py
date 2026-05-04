import json
import logging
import os
import re

import anthropic

from database import get_media_movil

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"

PALABRAS_CLAVE = [
    "urgente", "liquido", "liquidacion", "sucesion", "a refaccionar",
    "permuto", "directo", "acepto oferta", "oportunidad", "necesito vender",
    "bajo de precio", "ganga", "remato",
]

ZONAS_ALTA_DEMANDA = {"nordelta", "san-isidro", "palermo", "belgrano"}

TIPOS_PREFERIDOS = {"terrenos", "casas"}

SYSTEM_PROMPT = """Eres un experto en inversión inmobiliaria en Argentina (GBA Norte + CABA).
Tu tarea es evaluar propiedades para la estrategia: comprar subvaluado (USD 100k-200k),
mejorar y revender con ganancia.

Devuelve SIEMPRE un JSON con exactamente este formato (sin markdown, sin texto extra):
{"score": <entero 1-10>, "resumen": "<2-3 oraciones concisas>"}

Criterios de scoring (1=pésimo, 10=oportunidad excepcional):
- Precio/m² vs media de la zona (peso 40%): si está muy por debajo del promedio, sube el score
- Palabras clave de urgencia/oportunidad (peso 25%): urgente, liquido, sucesión, etc.
- Tipo de propiedad (peso 15%): terrenos y casas a refaccionar tienen más potencial
- Zona (peso 20%): nordelta/san-isidro/palermo/belgrano tienen mejor demanda para reventa
- Penalizar si el precio es demasiado alto para el m² dado o si la zona no es de las buscadas
"""


def _build_user_prompt(prop: dict, media_zona: float) -> str:
    delta = None
    if prop.get("precio_m2") and media_zona:
        delta = ((prop["precio_m2"] - media_zona) / media_zona) * 100

    delta_str = f"{delta:+.1f}%" if delta is not None else "desconocido"

    return f"""Propiedad a evaluar:
- Título: {prop.get("titulo", "N/A")}
- Fuente: {prop.get("fuente", "N/A")}
- Tipo: {prop.get("tipo", "N/A")}
- Zona: {prop.get("zona", "N/A")}
- Precio: USD {prop.get("precio_usd", "N/A"):,}
- Superficie: {prop.get("m2", "N/A")} m²
- Precio/m²: USD {prop.get("precio_m2", "N/A")}
- Media zona ({prop.get("zona")}): USD {media_zona:.0f}/m²
- Delta vs zona: {delta_str}
- Descripción: {prop.get("descripcion", "")}

Evalúa esta propiedad y devuelve el JSON."""


def analizar_propiedad(prop: dict) -> dict:
    """Analiza una propiedad con Claude. Retorna prop enriquecida con score y resumen."""
    zona = prop.get("zona", "default")
    media_zona = get_media_movil(zona)

    # pre-scoring rápido sin API para filtrar obviamente malos
    precio_usd = prop.get("precio_usd") or 0
    if precio_usd < 50_000 or precio_usd > 250_000:
        prop["score"] = 1
        prop["resumen"] = "Fuera de rango de precio objetivo."
        return prop

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": _build_user_prompt(prop, media_zona)}
            ],
        )
        raw = response.content[0].text.strip()

        # extraer JSON aunque venga con texto alrededor
        json_match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            data = json.loads(raw)

        prop["score"] = int(data.get("score", 5))
        prop["resumen"] = data.get("resumen", "Sin resumen.")
        logger.debug("Score %s → %d", prop.get("titulo", "")[:40], prop["score"])

    except json.JSONDecodeError as e:
        logger.warning("JSON inválido de Claude para %s: %s", prop.get("url"), e)
        prop["score"] = _score_heuristico(prop, media_zona)
        prop["resumen"] = "Análisis heurístico (error API)."
    except Exception as e:
        logger.error("Error Claude API: %s", e)
        prop["score"] = _score_heuristico(prop, media_zona)
        prop["resumen"] = "Análisis heurístico (error API)."

    return prop


def _score_heuristico(prop: dict, media_zona: float) -> int:
    """Score de respaldo sin API."""
    score = 5

    precio_m2 = prop.get("precio_m2") or 0
    if precio_m2 and media_zona:
        delta_pct = (precio_m2 - media_zona) / media_zona
        if delta_pct < -0.30:
            score += 3
        elif delta_pct < -0.15:
            score += 2
        elif delta_pct < -0.05:
            score += 1
        elif delta_pct > 0.20:
            score -= 2

    desc = (prop.get("descripcion", "") + " " + prop.get("titulo", "")).lower()
    kw_hits = sum(1 for kw in PALABRAS_CLAVE if kw in desc)
    score += min(kw_hits, 2)

    if prop.get("tipo") in TIPOS_PREFERIDOS:
        score += 1

    if prop.get("zona") in ZONAS_ALTA_DEMANDA:
        score += 1

    return max(1, min(10, score))


def analizar_lote(props: list[dict]) -> list[dict]:
    """Analiza una lista completa, devuelve lista enriquecida."""
    analizadas = []
    for i, prop in enumerate(props):
        logger.info("Analizando %d/%d: %s", i + 1, len(props), prop.get("url", "")[:60])
        try:
            analizadas.append(analizar_propiedad(prop))
        except Exception as e:
            logger.error("Fallo análisis prop %s: %s", prop.get("url"), e)
            prop.setdefault("score", 1)
            prop.setdefault("resumen", "Error en análisis.")
            analizadas.append(prop)
    return analizadas
