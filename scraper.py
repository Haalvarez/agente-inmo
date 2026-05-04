import re
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

ZONAS = [
    "tigre", "nordelta", "delta", "rincon-de-milberg",
    "general-pacheco", "don-torcuato", "benavidez",
    "san-isidro", "belgrano", "palermo", "caballito", "villa-urquiza",
]

TIPOS = ["casas", "terrenos", "ph", "departamentos"]

PRECIO_MIN_USD = 100_000
PRECIO_MAX_USD = 200_000

# ───────────────────────── MercadoLibre ─────────────────────────

ML_BASE = "https://inmuebles.mercadolibre.com.ar/{tipo}/venta/{zona}/_PriceRange_{min}USD-{max}USD"


def _parse_ml_price(text: str) -> float | None:
    m = re.search(r"USD\s*([\d.,]+)", text)
    if m:
        return float(m.group(1).replace(".", "").replace(",", "."))
    return None


def _parse_m2(text: str) -> float | None:
    m = re.search(r"([\d.,]+)\s*m[²2]", text, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def scrape_mercadolibre(zona: str, tipo: str, page) -> list[dict]:
    url = ML_BASE.format(tipo=tipo, zona=zona,
                         min=PRECIO_MIN_USD, max=PRECIO_MAX_USD)
    results = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(3000)

        items = page.query_selector_all(".ui-search-layout__item")
        if not items:
            items = page.query_selector_all("[class*='results-item']")

        for item in items[:20]:
            try:
                titulo_el = item.query_selector("h2, .ui-search-item__title")
                titulo = titulo_el.inner_text().strip() if titulo_el else ""

                link_el = item.query_selector("a.ui-search-item__group__element, a[href*='MLA']")
                if not link_el:
                    link_el = item.query_selector("a")
                href = link_el.get_attribute("href") if link_el else None
                if not href:
                    continue

                precio_el = item.query_selector(
                    ".andes-money-amount__fraction, "
                    "[class*='price__fraction'], "
                    ".price-tag-fraction"
                )
                currency_el = item.query_selector(
                    ".andes-money-amount__currency-symbol, "
                    "[class*='price__symbol']"
                )
                precio_usd = None
                if precio_el:
                    currency = currency_el.inner_text().strip() if currency_el else ""
                    raw = (currency + " " + precio_el.inner_text()).strip()
                    precio_usd = _parse_ml_price(raw) if "USD" in raw.upper() else None

                # buscar m2 en atributos
                m2 = None
                attr_els = item.query_selector_all(
                    ".ui-search-card-attributes__attribute, "
                    "[class*='attributes']"
                )
                desc_parts = []
                for attr in attr_els:
                    t = attr.inner_text().strip()
                    desc_parts.append(t)
                    if m2 is None:
                        m2 = _parse_m2(t)

                descripcion = " | ".join(desc_parts)
                precio_m2 = (precio_usd / m2) if (precio_usd and m2) else None

                results.append({
                    "fuente": "mercadolibre",
                    "titulo": titulo,
                    "url": href.split("?")[0],
                    "precio_usd": precio_usd,
                    "m2": m2,
                    "precio_m2": precio_m2,
                    "zona": zona,
                    "tipo": tipo,
                    "descripcion": descripcion,
                })
            except Exception as e:
                logger.debug("Error parseando item ML: %s", e)

        logger.info("ML %s/%s → %d propiedades", tipo, zona, len(results))
    except PWTimeout:
        logger.warning("Timeout ML %s/%s", tipo, zona)
    except Exception as e:
        logger.error("Error scraping ML %s/%s: %s", tipo, zona, e)

    return results


# ───────────────────────── Zonaprop ─────────────────────────

ZP_BASE = "https://www.zonaprop.com.ar/{tipo}-venta-{zona}.html"

ZP_TIPO_MAP = {
    "casas": "casas",
    "terrenos": "terrenos",
    "ph": "ph",
    "departamentos": "departamentos",
}


def scrape_zonaprop(zona: str, tipo: str, page) -> list[dict]:
    zp_tipo = ZP_TIPO_MAP.get(tipo, tipo)
    url = ZP_BASE.format(tipo=zp_tipo, zona=zona)
    results = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(4000)

        items = page.query_selector_all("[data-qa='posting PROPERTY']")
        if not items:
            items = page.query_selector_all(".postingCardLayout-module__posting-card")
        if not items:
            items = page.query_selector_all("[class*='postingCard']")

        for item in items[:20]:
            try:
                titulo_el = item.query_selector(
                    "[data-qa='POSTING_CARD_DESCRIPTION'], "
                    "[class*='title'], h2, h3"
                )
                titulo = titulo_el.inner_text().strip() if titulo_el else ""

                link_el = item.query_selector("a")
                href = link_el.get_attribute("href") if link_el else None
                if not href:
                    continue
                if href.startswith("/"):
                    href = "https://www.zonaprop.com.ar" + href

                precio_el = item.query_selector(
                    "[data-qa='POSTING_CARD_PRICE'], "
                    "[class*='price']"
                )
                precio_text = precio_el.inner_text().strip() if precio_el else ""
                precio_usd = None
                if "USD" in precio_text.upper() or "U$S" in precio_text.upper():
                    nums = re.findall(r"[\d.]+", precio_text)
                    if nums:
                        precio_usd = float(nums[0].replace(".", ""))
                        if precio_usd < 1000:
                            precio_usd *= 1000

                # m2 desde atributos
                m2 = None
                feature_els = item.query_selector_all(
                    "[data-qa='POSTING_CARD_FEATURES'] span, "
                    "[class*='feature'] span, "
                    "[class*='attribute']"
                )
                desc_parts = []
                for feat in feature_els:
                    t = feat.inner_text().strip()
                    if t:
                        desc_parts.append(t)
                    if m2 is None:
                        m2 = _parse_m2(t)

                descripcion = " | ".join(desc_parts)
                precio_m2 = (precio_usd / m2) if (precio_usd and m2) else None

                # filtro de precio
                if precio_usd and (precio_usd < PRECIO_MIN_USD or precio_usd > PRECIO_MAX_USD):
                    continue

                results.append({
                    "fuente": "zonaprop",
                    "titulo": titulo,
                    "url": href.split("?")[0],
                    "precio_usd": precio_usd,
                    "m2": m2,
                    "precio_m2": precio_m2,
                    "zona": zona,
                    "tipo": tipo,
                    "descripcion": descripcion,
                })
            except Exception as e:
                logger.debug("Error parseando item ZP: %s", e)

        logger.info("ZP %s/%s → %d propiedades", tipo, zona, len(results))
    except PWTimeout:
        logger.warning("Timeout ZP %s/%s", tipo, zona)
    except Exception as e:
        logger.error("Error scraping ZP %s/%s: %s", tipo, zona, e)

    return results


# ───────────────────────── Runner principal ─────────────────────────

def run_scraping() -> list[dict]:
    all_props = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="es-AR",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        for zona in ZONAS:
            for tipo in TIPOS:
                try:
                    props = scrape_mercadolibre(zona, tipo, page)
                    all_props.extend(props)
                except Exception as e:
                    logger.error("ML fallo %s/%s: %s", zona, tipo, e)

                try:
                    props = scrape_zonaprop(zona, tipo, page)
                    all_props.extend(props)
                except Exception as e:
                    logger.error("ZP fallo %s/%s: %s", zona, tipo, e)

        context.close()
        browser.close()

    # deduplicar por URL
    seen = set()
    unique = []
    for p in all_props:
        if p["url"] not in seen:
            seen.add(p["url"])
            unique.append(p)

    logger.info("Scraping completo: %d propiedades únicas", len(unique))
    return unique
