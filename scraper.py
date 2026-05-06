import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

CATEGORIAS = {
    "departamento": "MLA1459",
    "casa":         "MLA1468",
    "terreno":      "MLA1474",
}

STATE_ID = "TUxBUEdCUw"
BASE_URL  = "https://api.mercadolibre.com/sites/MLA/search"
PAGES     = 2
PAGE_SIZE = 50


def _extraer_m2(attributes: list) -> float | None:
    priority = ["COVERED_AREA", "TOTAL_AREA", "LAND_AREA"]
    attr_map = {a["id"]: a.get("value_name") for a in attributes}
    for key in priority:
        val = attr_map.get(key)
        if val:
            try:
                return float(val.replace(",", ".").split()[0])
            except (ValueError, IndexError):
                continue
    return None


def _fetch_categoria(tipo: str, categoria_id: str) -> list[dict]:
    results = []
    seen_ids: set[str] = set()

    for page in range(PAGES):
        offset = page * PAGE_SIZE
        try:
            resp = requests.get(
                BASE_URL,
                params={
                    "category": categoria_id,
                    "state_id":  STATE_ID,
                    "sort":      "date_desc",
                    "limit":     PAGE_SIZE,
                    "offset":    offset,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Error API ML %s offset=%d: %s", tipo, offset, e)
            break

        items = data.get("results", [])
        if not items:
            break

        for item in items:
            item_id = str(item.get("id", ""))
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            if item.get("currency_id") != "USD":
                continue
            precio_usd = item.get("price")
            if precio_usd is None:
                continue

            m2       = _extraer_m2(item.get("attributes", []))
            precio_m2 = (precio_usd / m2) if (m2 and m2 > 0) else None

            loc    = item.get("location", {})
            ciudad = (loc.get("city")         or {}).get("name")
            barrio = (loc.get("neighborhood") or {}).get("name")
            estado = (loc.get("state")        or {}).get("name")
            zona   = ciudad or estado or "GBA Norte"

            results.append({
                "id":             item_id,
                "fuente":         "mercadolibre",
                "titulo":         item.get("title", ""),
                "url":            item.get("permalink", ""),
                "precio_usd":     precio_usd,
                "moneda":         item.get("currency_id"),
                "m2":             m2,
                "precio_m2":      precio_m2,
                "tipo":           tipo,
                "zona":           zona,
                "ciudad":         ciudad,
                "barrio":         barrio,
                "descripcion":    "",
                "fecha_scraping": datetime.utcnow().isoformat(),
            })

    logger.info("ML %s → %d propiedades USD", tipo, len(results))
    return results


def run_scraping() -> list[dict]:
    all_props: list[dict] = []
    seen_ids:  set[str]   = set()

    for tipo, cat_id in CATEGORIAS.items():
        try:
            props = _fetch_categoria(tipo, cat_id)
            for p in props:
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    all_props.append(p)
        except Exception as e:
            logger.error("Fallo categoría %s: %s", tipo, e)

    logger.info("Scraping completo: %d propiedades únicas USD", len(all_props))
    return all_props
