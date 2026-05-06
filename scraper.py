import logging
import os
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

CATEGORIAS = {
    "departamento": "MLA1459",
    "casa":         "MLA1468",
    "terreno":      "MLA1474",
}

BASE_URL      = "https://api.mercadolibre.com/sites/MLA/search"
TOKEN_URL     = "https://api.mercadolibre.com/oauth/token"
PAGES         = 2
PAGE_SIZE     = 50

# Cache del token en memoria (se renueva si expiró)
_token_cache: dict = {"access_token": None, "expires_at": datetime.min}


def _get_token() -> str:
    """Obtiene un access_token usando client_credentials. Cachea hasta que expire."""
    global _token_cache

    if _token_cache["access_token"] and datetime.utcnow() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    client_id     = os.environ["ML_CLIENT_ID"]
    client_secret = os.environ["ML_CLIENT_SECRET"]

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    access_token = data["access_token"]
    # ML devuelve expires_in en segundos; restamos 60s de margen
    expires_in   = int(data.get("expires_in", 21600)) - 60
    expires_at   = datetime.utcnow() + timedelta(seconds=expires_in)

    _token_cache = {"access_token": access_token, "expires_at": expires_at}
    logger.info("Token ML renovado, expira en %ds", expires_in)
    return access_token


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


def _fetch_categoria(tipo: str, categoria_id: str, token: str) -> list[dict]:
    results   = []
    seen_ids: set[str] = set()
    headers   = {"Authorization": f"Bearer {token}"}

    for page in range(PAGES):
        offset = page * PAGE_SIZE
        try:
            resp = requests.get(
                BASE_URL,
                params={
                    "category": categoria_id,
                    "sort":     "date_desc",
                    "limit":    PAGE_SIZE,
                    "offset":   offset,
                },
                headers=headers,
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

            m2        = _extraer_m2(item.get("attributes", []))
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
    try:
        token = _get_token()
    except Exception as e:
        logger.error("No se pudo obtener token ML: %s", e)
        return []

    all_props: list[dict] = []
    seen_ids:  set[str]   = set()

    for tipo, cat_id in CATEGORIAS.items():
        try:
            props = _fetch_categoria(tipo, cat_id, token)
            for p in props:
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    all_props.append(p)
        except Exception as e:
            logger.error("Fallo categoría %s: %s", tipo, e)

    logger.info("Scraping completo: %d propiedades únicas USD", len(all_props))
    return all_props
