import sqlite3
import logging
import os
from datetime import datetime, timedelta
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "propiedades.db")

FALLBACK_PRECIO_M2 = {
    "tigre": 1200,
    "nordelta": 2200,
    "san-isidro": 2800,
    "don-torcuato": 900,
    "belgrano": 2500,
    "palermo": 3000,
    "caballito": 2200,
    "villa-urquiza": 1800,
    "delta": 1100,
    "rincon-de-milberg": 1000,
    "general-pacheco": 800,
    "benavidez": 900,
    "default": 1100,
}


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS propiedades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                fuente      TEXT NOT NULL,
                titulo      TEXT,
                url         TEXT UNIQUE NOT NULL,
                precio_usd  REAL,
                m2          REAL,
                precio_m2   REAL,
                zona        TEXT,
                tipo        TEXT,
                descripcion TEXT,
                score       INTEGER DEFAULT 0,
                resumen     TEXT,
                visto_en    TEXT DEFAULT (datetime('now')),
                notificado  INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_zona ON propiedades(zona)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_score ON propiedades(score)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visto ON propiedades(visto_en)")
    logger.info("Base de datos inicializada")


def upsert_propiedad(prop: dict) -> tuple[int, bool]:
    """Inserta o actualiza. Retorna (id, es_nueva)."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM propiedades WHERE url = ?", (prop["url"],)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE propiedades SET
                    precio_usd=?, m2=?, precio_m2=?, score=?, resumen=?,
                    visto_en=datetime('now')
                   WHERE url=?""",
                (
                    prop.get("precio_usd"),
                    prop.get("m2"),
                    prop.get("precio_m2"),
                    prop.get("score", 0),
                    prop.get("resumen"),
                    prop["url"],
                ),
            )
            return existing["id"], False

        conn.execute(
            """INSERT INTO propiedades
               (fuente, titulo, url, precio_usd, m2, precio_m2, zona,
                tipo, descripcion, score, resumen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                prop.get("fuente"),
                prop.get("titulo"),
                prop["url"],
                prop.get("precio_usd"),
                prop.get("m2"),
                prop.get("precio_m2"),
                prop.get("zona"),
                prop.get("tipo"),
                prop.get("descripcion"),
                prop.get("score", 0),
                prop.get("resumen"),
            ),
        )
        return conn.lastrowid, True


def marcar_notificado(prop_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE propiedades SET notificado=1 WHERE id=?", (prop_id,)
        )


def get_pendientes_notificar(min_score: int = 7, limit: int = 5) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM propiedades
               WHERE score >= ? AND notificado = 0
               ORDER BY score DESC
               LIMIT ?""",
            (min_score, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all(filters: dict | None = None) -> list[dict]:
    query = "SELECT * FROM propiedades WHERE 1=1"
    params: list = []
    if filters:
        if filters.get("zona"):
            query += " AND zona = ?"
            params.append(filters["zona"])
        if filters.get("tipo"):
            query += " AND tipo = ?"
            params.append(filters["tipo"])
        if filters.get("min_score") is not None:
            query += " AND score >= ?"
            params.append(filters["min_score"])
    query += " ORDER BY score DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_media_movil(zona: str, ventana_dias: int = 60, min_muestras: int = 5) -> float:
    """Media móvil de precio/m² con remoción de outliers IQR."""
    desde = (datetime.utcnow() - timedelta(days=ventana_dias)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT precio_m2 FROM propiedades
               WHERE zona = ? AND precio_m2 IS NOT NULL
                 AND precio_m2 > 0 AND visto_en >= ?""",
            (zona, desde),
        ).fetchall()

    valores = [r["precio_m2"] for r in rows]
    if len(valores) < min_muestras:
        fallback = FALLBACK_PRECIO_M2.get(zona, FALLBACK_PRECIO_M2["default"])
        logger.debug("Media móvil fallback para %s: %s", zona, fallback)
        return float(fallback)

    valores.sort()
    n = len(valores)
    q1 = valores[n // 4]
    q3 = valores[(3 * n) // 4]
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    limpios = [v for v in valores if lower <= v <= upper]

    if not limpios:
        return float(FALLBACK_PRECIO_M2.get(zona, FALLBACK_PRECIO_M2["default"]))

    media = sum(limpios) / len(limpios)
    logger.debug("Media móvil %s: %.0f (n=%d)", zona, media, len(limpios))
    return media


def get_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM propiedades").fetchone()[0]
        ultima = conn.execute(
            "SELECT MAX(visto_en) FROM propiedades"
        ).fetchone()[0]
    return {"total": total, "ultima_actualizacion": ultima}
