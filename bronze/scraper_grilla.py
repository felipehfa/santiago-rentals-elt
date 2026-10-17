"""Scraper de grilla -> Bronze.

Por cada comuna x tipo recorre las páginas de resultados, guarda el HTML crudo en el landing local y las
tarjetas (strings crudos, sin limpiar) en bronze.grilla_avisos. Ver bronze/sql/001_schema.sql.

Uso:
    python bronze/scraper_grilla.py                       # todas las comunas de config.COMUNAS_RM
    python bronze/scraper_grilla.py --comunas quilicura-metropolitana --max-paginas 2
    python bronze/scraper_grilla.py --sin-bd              # solo landing, sin escribir en Supabase
"""
import argparse
import gzip
import hashlib
import json
import logging
import math
import random
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from psycopg2.extras import Json, execute_values

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import config  # noqa: E402
from common.db import conectar  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("grilla")

RE_ID_AVISO = re.compile(r"(MLC-\d+)")
RE_TOTAL = re.compile(r"([\d.]+)\s+resultados", re.IGNORECASE)
RE_DORMITORIOS = re.compile(r"(\d+)\s*dormitorios?", re.IGNORECASE)
RE_BANOS = re.compile(r"(\d+)\s*ba[ñn]os?", re.IGNORECASE)
RE_M2 = re.compile(r"([\d.,]+)\s*m[²2]\b", re.IGNORECASE)

# Solo `li`: los selectores `div.ui-search-result__wrapper` / `div.andes-card` también capturan contenedores
# de publicidad y carruseles (53 "tarjetas" en Vitacura cuando la página tiene 48 avisos).
SEL_TARJETA = "li.ui-search-layout__item"
SEL_TITULO = ["h3.poly-component__title", "h2.ui-search-item__title", "a.poly-component__title"]
SEL_LINK = ["a.poly-component__title", "a.ui-search-link"]
SEL_UBICACION = ["span.poly-component__location", "span.ui-search-item__location"]

MAX_COMBOS_ANOMALOS_SEGUIDOS = 3  # combos comuna x tipo cuya página 1 viene vacía antes de dar por bloqueada la IP


class Bloqueado(Exception):
    """El sitio dejó de entregar resultados: abortar la corrida en vez de registrar 'success' con 0 filas."""


def _primero(tag, selectores: list[str]):
    for sel in selectores:
        el = tag.select_one(sel)
        if el:
            return el
    return None


def _texto(el) -> Optional[str]:
    return el.get_text(strip=True) if el else None


Segmento = tuple[int, int]  # rango de precio en CLP (min, max); max=0 significa "sin tope"

# El sitio corta cada búsqueda en la página 42 (2.016 resultados) con un 404. Una búsqueda que declara más que
# este umbral se parte en rangos de precio; el margen bajo 2.016 deja espacio para que el mercado crezca.
UMBRAL_SEGMENTAR = 1800
ESCALERA_PRECIO: list[Segmento] = [(0, 300_000), (300_000, 400_000), (400_000, 500_000),
                                   (500_000, 700_000), (700_000, 0)]
PASO_PRECIO = 10_000


def texto_segmento(segmento: Optional[Segmento]) -> Optional[str]:
    return f"{segmento[0]}-{segmento[1]}" if segmento else None


def construir_url(tipo: str, comuna: str, pagina: int, segmento: Optional[Segmento] = None) -> str:
    base = f"{config.BASE_URL}/{config.OPERACION}/{tipo}/{comuna}"
    filtro = f"_PriceRange_{segmento[0]}CLP-{segmento[1]}CLP" if segmento else ""
    if pagina == 1:
        return f"{base}/{filtro}" if filtro else base
    offset = 1 + (pagina - 1) * config.RESULTADOS_POR_PAGINA
    return f"{base}/_Desde_{offset}_{filtro}_NoIndex_True" if filtro else f"{base}/_Desde_{offset}_NoIndex_True"


def dividir_segmento(segmento: Segmento) -> list[Segmento]:
    """Parte un rango de precio en dos. Los bordes del sitio no son disjuntos (los avisos en UF se convierten
    a pesos con redondeo), así que hay duplicados entre segmentos; se absorben por ID. [] si ya no se puede partir."""
    lo, hi = segmento
    if hi == 0:
        mid = round(lo * 1.5 / PASO_PRECIO) * PASO_PRECIO
        return [(lo, mid), (mid, 0)]
    mid = round((lo + hi) / 2 / PASO_PRECIO) * PASO_PRECIO
    return [(lo, mid), (mid, hi)] if lo < mid < hi else []


def pedir_html(url: str, reintentos: int = 3) -> tuple[Optional[int], Optional[str]]:
    """(status, html). status None si no hubo respuesta tras los reintentos."""
    status = None
    for intento in range(1, reintentos + 1):
        try:
            resp = requests.get(url, headers=config.HEADERS, timeout=20)
            status = resp.status_code
            if status == 200:
                return status, resp.text
            if status in (403, 429):
                raise Bloqueado(f"HTTP {status} en {url}")
            if status == 404:
                return status, None
        except requests.RequestException as e:
            log.warning("Error de red (%s/%s) en %s: %s", intento, reintentos, url, e)
        time.sleep(5 * intento)
    return status, None


def parsear_tarjetas(html: str) -> list[dict]:
    """Strings crudos de cada tarjeta. Nada se convierte a número: eso es trabajo de Silver."""
    soup = BeautifulSoup(html, "lxml")
    tarjetas = []
    for t in soup.select(SEL_TARJETA):
        link = _primero(t, SEL_LINK)
        url = link.get("href") if link else None
        m_id = RE_ID_AVISO.search(url or "")
        if not m_id:
            continue

        # Un aviso con rebaja trae dos widgets de precio: el "antes" tachado y el vigente.
        vigente = t.select_one(".andes-money-amount.poly-price__amount")
        anterior = t.select_one(".andes-money-amount--previous")
        texto = t.get_text(" ", strip=True)
        m_dorm, m_ban, m_m2 = RE_DORMITORIOS.search(texto), RE_BANOS.search(texto), RE_M2.search(texto)

        tarjetas.append({
            "id_aviso": m_id.group(1),
            "titulo": _texto(_primero(t, SEL_TITULO)),
            "precio": _texto(vigente.select_one("span.andes-money-amount__fraction")) if vigente else None,
            "moneda": _texto(vigente.select_one("span.andes-money-amount__currency-symbol")) if vigente else None,
            "precio_anterior": _texto(anterior.select_one("span.andes-money-amount__fraction")) if anterior else None,
            "ubicacion": _texto(_primero(t, SEL_UBICACION)),
            "dormitorios": m_dorm.group(1) if m_dorm else None,
            "banos": m_ban.group(1) if m_ban else None,
            "superficie_m2": m_m2.group(1) if m_m2 else None,
            "url": url.split("#", 1)[0],
            # Trae tracking_id aleatorio y la posición en la página: se guarda (es crudo) pero no entra al hash.
            "url_fragmento": url.split("#", 1)[1] if "#" in url else None,
            "texto_tarjeta": texto,
        })
    return tarjetas


def total_declarado(html: str) -> Optional[int]:
    m = RE_TOTAL.search(BeautifulSoup(html, "lxml").get_text(" ", strip=True))
    return int(m.group(1).replace(".", "")) if m else None


def guardar_landing(html: str, tipo: str, comuna: str, pagina: int,
                    segmento: Optional[Segmento] = None) -> tuple[str, str]:
    """HTML crudo comprimido. Devuelve (ruta relativa a RAIZ, sha256 del HTML)."""
    carpeta = config.RUTA_LANDING / date.today().isoformat() / tipo / comuna
    if segmento:
        carpeta = carpeta / f"seg_{texto_segmento(segmento)}"
    ruta = carpeta / f"p{pagina:03d}.html.gz"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    crudo = html.encode("utf-8")
    ruta.write_bytes(gzip.compress(crudo))
    return str(ruta.relative_to(RAIZ)).replace("\\", "/"), hashlib.sha256(crudo).hexdigest()


CAMPOS_VOLATILES = {"url_fragmento"}  # cambian en cada request aunque el aviso sea idéntico


def hash_payload(payload: dict) -> str:
    estable = {k: v for k, v in payload.items() if k not in CAMPOS_VOLATILES}
    return hashlib.sha256(json.dumps(estable, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ persistencia

def iniciar_run(con, fuente: str) -> int:
    with con, con.cursor() as cur:
        cur.execute("INSERT INTO bronze.runs (fuente) VALUES (%s) RETURNING run_id", (fuente,))
        return cur.fetchone()[0]


def cerrar_run(con, run_id: int, estado: str, paginas: int, filas: int, detalle: Optional[str]) -> None:
    with con, con.cursor() as cur:
        cur.execute(
            "UPDATE bronze.runs SET fin=now(), estado=%s, paginas=%s, filas_nuevas=%s, detalle=%s WHERE run_id=%s",
            (estado, paginas, filas, detalle, run_id),
        )


def registrar_pagina(con, run_id, comuna, tipo, pagina, url, status, n_tarjetas, total, html_path, sha,
                     segmento: Optional[str] = None) -> None:
    with con, con.cursor() as cur:
        cur.execute(
            """INSERT INTO bronze.grilla_paginas
               (run_id, comuna, tipo_propiedad, pagina, url, http_status, n_tarjetas, total_declarado,
                html_path, html_sha256, segmento) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, comuna, tipo, pagina, url, status, n_tarjetas, total, html_path, sha, segmento),
        )


def registrar_cobertura(con, run_id, comuna, tipo, segmentada, total, unicos, estado) -> None:
    with con, con.cursor() as cur:
        cur.execute(
            """INSERT INTO bronze.grilla_cobertura
               (run_id, comuna, tipo_propiedad, segmentada, total_declarado, avisos_unicos, estado)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, comuna, tipo, segmentada, total, unicos, estado),
        )


def guardar_tarjetas(con, run_id: int, comuna: str, tipo: str, pagina: int, tarjetas: list[dict]) -> int:
    """Inserta solo los avisos cuyo payload cambió. Devuelve cuántas filas nuevas entraron."""
    if not tarjetas:
        return 0
    ids = [t["id_aviso"] for t in tarjetas]
    with con, con.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (id_aviso) id_aviso, hash_payload FROM bronze.grilla_avisos
               WHERE id_aviso = ANY(%s) ORDER BY id_aviso, scraped_at DESC""",
            (ids,),
        )
        ultimo = dict(cur.fetchall())

        nuevas = []
        for t in tarjetas:
            payload = {k: v for k, v in t.items() if k != "id_aviso"}
            h = hash_payload(payload)
            if ultimo.get(t["id_aviso"]) != h:
                nuevas.append((t["id_aviso"], comuna, tipo, config.OPERACION, run_id, pagina, h, Json(payload)))
        if nuevas:
            execute_values(
                cur,
                """INSERT INTO bronze.grilla_avisos
                   (id_aviso, comuna, tipo_propiedad, operacion, run_id, pagina, hash_payload, payload)
                   VALUES %s""",
                nuevas,
            )
        # `ultima_vez` se actualiza siempre, aunque el payload no haya cambiado.
        execute_values(
            cur,
            """INSERT INTO bronze.grilla_vistos (id_aviso, primera_vez, ultima_vez, ultimo_run_id)
               VALUES %s
               ON CONFLICT (id_aviso) DO UPDATE
               SET ultima_vez = EXCLUDED.ultima_vez, ultimo_run_id = EXCLUDED.ultimo_run_id""",
            [(i, run_id) for i in ids],
            template="(%s, now(), now(), %s)",
        )
    return len(nuevas)


# ------------------------------------------------------------------ orquestación de la corrida

class Progreso:
    """Contadores de la corrida, compartidos entre las búsquedas."""
    def __init__(self) -> None:
        self.paginas = 0
        self.filas = 0
        self.anomalos_seguidos = 0


def scrapear_busqueda(con, run_id: int, prog: Progreso, comuna: str, tipo: str, segmento: Optional[Segmento],
                      max_paginas: Optional[int], vistos: set, segmentar: bool) -> tuple[Optional[int], bool]:
    """Recorre las páginas de UNA búsqueda (comuna x tipo, con o sin rango de precio).

    Devuelve (total declarado, demasiado_grande). Con segmentar=True, una búsqueda que declara más que
    UMBRAL_SEGMENTAR se corta tras la página 1 (que igual se guarda) y devuelve demasiado_grande=True: el
    llamador la parte en rangos de precio, porque seguir pidiendo páginas toparía con el 404 de la página 43.
    """
    pagina, tarjetas_busqueda, total = 1, 0, None
    while True:
        if max_paginas and pagina > max_paginas:
            break
        url = construir_url(tipo, comuna, pagina, segmento)
        status, html = pedir_html(url)
        prog.paginas += 1

        tarjetas = parsear_tarjetas(html) if html else []
        if pagina == 1 and html:
            total = total_declarado(html)
        html_path, sha = guardar_landing(html, tipo, comuna, pagina, segmento) if html else (None, None)
        if con:
            registrar_pagina(con, run_id, comuna, tipo, pagina, url, status, len(tarjetas),
                             total if pagina == 1 else None, html_path, sha, texto_segmento(segmento))

        if pagina == 1:
            # Página 1 sin tarjetas y sin que el sitio diga "0 resultados" = respuesta anómala.
            # El 17-oct-2026 GitHub Actions recibió 100 páginas vacías y cerró en 'success'.
            if not tarjetas and total != 0:
                prog.anomalos_seguidos += 1
                log.warning("Página 1 vacía en %s/%s %s (status=%s, total=%s)", comuna, tipo,
                            texto_segmento(segmento), status, total)
                if prog.anomalos_seguidos >= MAX_COMBOS_ANOMALOS_SEGUIDOS:
                    raise Bloqueado(f"{prog.anomalos_seguidos} búsquedas seguidas con página 1 vacía")
            else:
                prog.anomalos_seguidos = 0

        if not tarjetas:
            break
        if con:
            prog.filas += guardar_tarjetas(con, run_id, comuna, tipo, pagina, tarjetas)
        vistos.update(t["id_aviso"] for t in tarjetas)
        tarjetas_busqueda += len(tarjetas)
        log.info("%s %s %s p%d: %d tarjetas (%s declarados)", comuna, tipo, texto_segmento(segmento) or "-",
                 pagina, len(tarjetas), total)

        if segmentar and pagina == 1 and total is not None and total > UMBRAL_SEGMENTAR:
            return total, True
        if total is not None and tarjetas_busqueda >= total:
            break
        if len(tarjetas) < config.RESULTADOS_POR_PAGINA:
            break
        pagina += 1
        time.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))
    time.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))
    return total, False


def scrapear_en_segmentos(con, run_id, prog, comuna, tipo, segmento: Segmento, max_paginas, vistos) -> None:
    """Scrapea un rango de precio; si aún declara demasiado, lo parte a la mitad y sigue con cada mitad."""
    _, grande = scrapear_busqueda(con, run_id, prog, comuna, tipo, segmento, max_paginas, vistos, segmentar=True)
    if not grande:
        return
    partes = dividir_segmento(segmento)
    if not partes:
        log.warning("%s %s: rango %s ya no se puede partir; se captura hasta el tope del sitio",
                    comuna, tipo, texto_segmento(segmento))
        scrapear_busqueda(con, run_id, prog, comuna, tipo, segmento, max_paginas, vistos, segmentar=False)
        return
    for parte in partes:
        scrapear_en_segmentos(con, run_id, prog, comuna, tipo, parte, max_paginas, vistos)


def estado_cobertura(total: Optional[int], unicos: int, acotada: bool) -> str:
    """'completa' si se capturó lo que el sitio declara (con tolerancia por avisos que entran y salen
    mientras se recorre). Una corrida acotada con --max-paginas nunca es completa."""
    if acotada or total is None:
        return "parcial"
    return "completa" if unicos >= total - max(10, total // 100) else "parcial"


def scrapear(con, comunas: list[str], tipos: list[str], max_paginas: Optional[int]) -> tuple[int, int, str]:
    """Devuelve (páginas, filas nuevas, estado). Con con=None no escribe en la BD (solo landing)."""
    run_id = iniciar_run(con, "grilla") if con else 0
    prog = Progreso()
    estado, detalle = "success", None

    try:
        for comuna in comunas:
            for tipo in tipos:
                vistos: set = set()
                total, grande = scrapear_busqueda(con, run_id, prog, comuna, tipo, None, max_paginas, vistos,
                                                  segmentar=True)
                if grande:
                    log.info("%s %s declara %s resultados (> %d): se segmenta por precio",
                             comuna, tipo, total, UMBRAL_SEGMENTAR)
                    for segmento in ESCALERA_PRECIO:
                        scrapear_en_segmentos(con, run_id, prog, comuna, tipo, segmento, max_paginas, vistos)

                cobertura = estado_cobertura(total, len(vistos), acotada=bool(max_paginas))
                log.info("%s %s: %d avisos únicos de %s declarados -> %s", comuna, tipo, len(vistos), total, cobertura)
                if con:
                    registrar_cobertura(con, run_id, comuna, tipo, grande, total, len(vistos), cobertura)
                if cobertura != "completa" and estado == "success":
                    estado = "parcial"
    except Bloqueado as e:
        estado, detalle = "bloqueado", str(e)
        log.error("ABORTADO: %s", e)
    except Exception as e:  # noqa: BLE001 - se registra en runs y se relanza
        if con:
            cerrar_run(con, run_id, "error", prog.paginas, prog.filas, repr(e))
        raise

    if con:
        cerrar_run(con, run_id, estado, prog.paginas, prog.filas, detalle)
    return prog.paginas, prog.filas, estado



def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comunas", nargs="+", default=config.COMUNAS_RM)
    ap.add_argument("--tipos", nargs="+", default=config.TIPOS_PROPIEDAD)
    ap.add_argument("--max-paginas", type=int, default=None, help="tope por comuna x tipo (pruebas)")
    ap.add_argument("--sin-bd", action="store_true", help="solo guarda el landing, no escribe en Supabase")
    args = ap.parse_args()

    con = None if args.sin_bd else conectar()
    try:
        paginas, filas, estado = scrapear(con, args.comunas, args.tipos, args.max_paginas)
    finally:
        if con:
            con.close()
    log.info("Fin: estado=%s, páginas=%d, filas nuevas=%d", estado, paginas, filas)
    return 0 if estado == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
