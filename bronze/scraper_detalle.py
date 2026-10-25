"""Scraper de detalle -> Bronze. Primera visita y revisitas en un solo script.

Arma una cola de avisos a visitar, derivada con SQL de las tablas de la grilla y del log de intentos
(sin contadores mutables), en este orden de prioridad:
  1. nuevo          aviso que nunca se visitó con éxito
  2. desaparecido   dejó de aparecer en la última grilla exitosa: ¿pausado, finalizado o eliminado?
  3. tarjeta_cambio su tarjeta de la grilla cambió desde la última visita (probable cambio de precio)
  4. rotacion       activo sin revisar hace más de su intervalo (DIAS_ROTACION_TRAMOS, según su antigüedad)

Cada visita queda en bronze.detalle_intentos. Solo si lo observado cambió se agrega una fila a
bronze.detalle_avisos, con la evidencia cruda de estado y precio (la interpretación es de Silver).

Uso:
    python bronze/scraper_detalle.py --limite 300
    python bronze/scraper_detalle.py --limite 20 --motivos nuevo
    python bronze/scraper_detalle.py --limite 20000 --presupuesto-dia 1200   # tope de visitas en 24 h
"""
import argparse
import gzip
import hashlib
import json
import logging
import random
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from psycopg2.extras import Json

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import config  # noqa: E402
from common.db import ConexionResiliente  # noqa: E402

_RUTA_LOG = RAIZ / "logs" / "detalle.log"
_RUTA_LOG.parent.mkdir(exist_ok=True)
# Pantalla y archivo fijo (logs/detalle.log, fuera de git): el avance queda aunque la salida no se redirija.
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(_RUTA_LOG, encoding="utf-8")])
log = logging.getLogger("detalle")

# Rotación escalonada por antigüedad de la publicación: cada cuántos días se vuelve a visitar un aviso activo según tenga
# hasta 14, 30, 60, 120 o más de 120 días. Los recientes cambian más (bajan de precio o se arriendan en pocos días).
# Sin fecha = como reciente. Eran (1, 2, 4, 7, 14): pedían ~6.200 visitas diarias de rotación y caben ~3.200, así que la cola
# nunca se vaciaba y los avisos de más de 60 días no se revisaban nunca; solo el 10 % de esas visitas encontraba un cambio real
# (casi todo, avisos finalizados; los cambios de precio los detecta la tarjeta de la grilla). Bitácora P-29 (24-oct).
DIAS_ROTACION_TRAMOS = (2, 4, 7, 14, 30)
DIAS_ENTRE_VISITAS_DESAPARECIDO = 2
CADA_N_VISITAS_AVANCE = 50          # cada cuántas visitas se escribe una línea de avance
MAX_FALLOS_POR_AVISO = 5          # error/no_encontrado consecutivos antes de dejar de insistir en un aviso
HORAS_ENTRE_REINTENTOS = 12
MAX_FALLOS_SEGUIDOS_EN_CORRIDA = 8  # ver Bloqueado más abajo

# Ante un bloqueo (429, captcha o muro) no se aborta: se espera, se baja el ritmo y se reintenta el mismo aviso.
# El bloqueo parece una ventana por IP que se levanta sola (a los ~20 min la prueba pasó), y cada bloqueo registra
# cuántas visitas aguantó, para estimar el umbral real. Solo aborta si varios bloqueos seguidos no dejan avanzar.
ESPERA_BLOQUEO_S = 30 * 60
FACTOR_PAUSA_MAX = 8.0              # tope del multiplicador de las pausas entre visitas (se duplica en cada bloqueo)
RUTA_RITMO = RAIZ / "logs" / "detalle_ritmo.json"   # factor de pausa con que terminó la última corrida
VIGENCIA_RITMO_H = 2.0                             # pasado este tiempo, el sitio ya se recuperó y se vuelve al ritmo base
VISITAS_PARA_RELAJAR = 50          # visitas buenas seguidas tras las que las pausas vuelven a bajar (a la mitad, hasta x1)
MAX_BLOQUEOS_SEGUIDOS = 3           # bloqueos sin ninguna visita buena entre medio => abortar
# Códigos de salida: el orquestador decide qué hacer según cómo terminó el detalle.
CODIGOS_SALIDA = {"success": 0, "vacia": 5, "bloqueado": 1, "presupuesto": 4}
# Con menos visitas disponibles no se lanza una tanda: evita tandas de 5 o 10 visitas cada dos minutos al borde del tope.
MIN_VISITAS_TANDA = 50
PRESUPUESTO_24H = 5000              # visitas máximas en una ventana móvil de 24 h (--presupuesto-dia)

# El sitio, ante tráfico que clasifica como automatizado, puede redirigir CUALQUIER URL a un muro de
# verificación con status 200 y sin CAPTCHA visible. En el proyecto de Concepción eso marcó ~1.550 avisos
# activos como eliminados (agosto 2026). Se detecta por la URL final, no por el contenido.
RUTAS_MURO_VERIFICACION = ("/gz/account-verification", "/jms/mlc/lgz/login", "/registration-pi")

# Canonical de un proyecto: .../arriendo/departamento/<comuna>/888888359-lofty-nva. El ID numérico puede ser
# corto (12072-edificio-porvenir-nva) y el separador doble (11473--imu-san-cristobal-nva).
RE_CANONICAL_PROYECTO = re.compile(r"/arriendo/[^/]+/[^/]+/\d+-+[^/]+/?$")
RE_JSON_ESTADO = re.compile(r"_n\.ctx\.r=(\{.*?\});_n\.ctx\.r\.assets\.manifest=", re.DOTALL)
RE_FECHA_PUBLICACION = re.compile(r"Publicado (hoy|esta semana|hace [^\n\|]+)", re.IGNORECASE)
RE_SUPERFICIE_TOTAL = re.compile(r"Superficie total\s*([\d.,]+)\s*m", re.IGNORECASE)
RE_SUPERFICIE_UTIL = re.compile(r"Superficie útil\s*([\d.,]+)\s*m", re.IGNORECASE)
# Sin IGNORECASE a propósito en dormitorios y baños: el carrusel de "recomendados" y la insignia superior
# traen "N dormitorios" / "N baños" en minúscula de OTROS avisos o con otro orden (ver scraper de Concepción).
RE_DORMITORIOS = re.compile(r"Dormitorios\s*(\d+)")
RE_BANOS = re.compile(r"Baños\s*(\d+)")
RE_SI_NO = r":?\s*(Sí|No)"
PATRONES_TEXTO = {
    "estacionamientos": re.compile(r"Estacionamientos:?\s*(\d+)", re.IGNORECASE),
    "antiguedad_anos": re.compile(r"Antigüedad\s*(\d+)\s*años?", re.IGNORECASE),
    "amoblado": re.compile(r"Amoblado" + RE_SI_NO, re.IGNORECASE),
    "admite_mascotas": re.compile(r"Admite mascotas" + RE_SI_NO, re.IGNORECASE),
    "condominio_cerrado": re.compile(r"En condominio cerrado" + RE_SI_NO, re.IGNORECASE),
    "bodegas": re.compile(r"Bodegas\s*(\d+)", re.IGNORECASE),
    "estacionamiento_visitas": re.compile(r"Estacionamiento de visitas" + RE_SI_NO, re.IGNORECASE),
    "solo_familias": re.compile(r"Solo familias" + RE_SI_NO, re.IGNORECASE),
    "max_habitantes": re.compile(r"Cantidad máxima de habitantes\s*(\d+)", re.IGNORECASE),
    "piscina": re.compile(r"Piscina" + RE_SI_NO, re.IGNORECASE),
    "quincho": re.compile(r"Quincho\D{0,15}?" + RE_SI_NO, re.IGNORECASE),
    "conserjeria": re.compile(r"Conserjería" + RE_SI_NO, re.IGNORECASE),
    "ascensor": re.compile(r"Ascensor" + RE_SI_NO, re.IGNORECASE),
    "piso_unidad": re.compile(r"Número de piso de la unidad\s*(\d+)", re.IGNORECASE),
    "deptos_por_piso": re.compile(r"Departamentos por piso\s*(\d+)", re.IGNORECASE),
}
# "Gastos comunes" aparece dos veces: en la sección de características ("Gastos comunes" / "X CLP") y en la
# insignia de resumen ("Gastos comunes desde $ X"), que sirve de respaldo.
RE_GASTOS_COMUNES = re.compile(r"Gastos comunes:?\s*\$?\s*([\d.,]+)", re.IGNORECASE)
RE_GASTOS_COMUNES_RESUMEN = re.compile(r"Gastos comunes\s+desde\s*\$?\s*([\d.,]+)", re.IGNORECASE)
RE_LATITUD = re.compile(r'"latitude":"(-?[\d.]+)"')
RE_LONGITUD = re.compile(r'"longitude":"(-?[\d.]+)"')
RE_LATLON_MAPA = re.compile(r"center=(-?[\d.]+)%2C(-?[\d.]+)")
SELECTORES_DESCRIPCION = ["[data-testid='core-description'] p", "p.ui-pdp-description__content",
                          "div.ui-pdp-description"]

# Subcategorías de puntos de interés, tal como las nombra el sitio (sin tildes, en minúscula).
SUBCATEGORIAS_POI = {
    "paraderos": "paraderos", "estaciones de metro": "estaciones_metro",
    "jardines infantiles": "jardines_infantiles", "colegios": "colegios",
    "universidades": "universidades", "plazas": "plazas", "supermercados": "supermercados",
    "farmacias": "farmacias", "centros comerciales": "centros_comerciales",
    "hospitales": "hospitales", "clinicas": "clinicas",
}

# Cambian en cada visita aunque el aviso sea idéntico ("hace 3 días" avanza solo): se guardan pero no entran al hash.
CAMPOS_VOLATILES = {"fecha_publicacion_texto"}


class Bloqueado(Exception):
    """El sitio está frenando el tráfico: abortar sin interpretar nada como 'aviso eliminado'."""


# ------------------------------------------------------------------ extracción

def _sin_tildes(texto: str) -> str:
    for a, b in {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}.items():
        texto = texto.replace(a, b)
    return texto


def extraer_json_pagina(html: str) -> Optional[dict]:
    m = RE_JSON_ESTADO.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _componentes(estado: Optional[dict]) -> dict:
    try:
        comps = estado["appProps"]["pageProps"]["initialState"]["components"]
        return comps if isinstance(comps, dict) else {}
    except (KeyError, TypeError):
        return {}


def _buscar_por_id(nodo, ids: tuple):
    """Primer dict cuyo campo 'id' esté en ids, buscando en profundidad."""
    if isinstance(nodo, dict):
        if nodo.get("id") in ids:
            return nodo
        for v in nodo.values():
            r = _buscar_por_id(v, ids)
            if r is not None:
                return r
    elif isinstance(nodo, list):
        for v in nodo:
            r = _buscar_por_id(v, ids)
            if r is not None:
                return r
    return None


def extraer_estado_texto(comps: dict) -> Optional[str]:
    """Texto crudo del banner de estado ('Publicación finalizada'); None si el aviso no lo trae (activo)."""
    for clave in ("item_status_message", "item_status_short_description_message"):
        body = (comps.get(clave) or {}).get("body") if isinstance(comps.get(clave), dict) else None
        if isinstance(body, dict) and body.get("text"):
            return body["text"]
    for subarbol in (comps.get("head"), comps.get("short_description")):
        nodo = _buscar_por_id(subarbol, ("item_status_message", "item_status_short_description_message"))
        body = nodo.get("body") if nodo else None
        if isinstance(body, dict) and body.get("text"):
            return body["text"]
    return None


def extraer_precio(comps: dict) -> dict:
    """Precio vigente tal cual lo muestra la página, en su moneda original (CLP, CLF=UF, USD)."""
    precio = (comps.get("price") or {}).get("price") if isinstance(comps.get("price"), dict) else None
    if not isinstance(precio, dict):
        nodo = _buscar_por_id(comps.get("short_description"), ("price",))
        precio = nodo.get("price") if nodo else None
    precio = precio if isinstance(precio, dict) else {}
    return {"precio_valor": precio.get("value"), "precio_moneda": precio.get("currency_id"),
            "precio_original": precio.get("original_value")}


def _buscar_clave(nodo, clave: str):
    """Primer valor no vacío de `clave` en cualquier parte del JSON (el sitio repite bloques, algunos vacíos)."""
    if isinstance(nodo, dict):
        if nodo.get(clave):
            return nodo[clave]
        for v in nodo.values():
            r = _buscar_clave(v, clave)
            if r:
                return r
    elif isinstance(nodo, list):
        for v in nodo:
            r = _buscar_clave(v, clave)
            if r:
                return r
    return None


def _buscar_categorias_poi(nodo) -> Optional[list]:
    if isinstance(nodo, dict):
        cats = nodo.get("categories")
        if isinstance(cats, list) and cats and isinstance(cats[0], dict) and "subcategories" in cats[0]:
            return cats
        for v in nodo.values():
            r = _buscar_categorias_poi(v)
            if r:
                return r
    elif isinstance(nodo, list):
        for v in nodo:
            r = _buscar_categorias_poi(v)
            if r:
                return r
    return None


def extraer_poi_crudo(estado: Optional[dict]) -> dict:
    """Subtítulos crudos ('0 mins - 15 metros') por subcategoría. El radio de 500 m es decisión de Silver."""
    salida: dict = {}
    cats = _buscar_categorias_poi(estado) if estado else None
    for cat in cats or []:
        for sub in cat.get("subcategories", []):
            nombre = _sin_tildes((sub.get("title") or {}).get("text", "").lower().strip())
            clave = SUBCATEGORIAS_POI.get(nombre)
            if not clave:
                continue
            salida[clave] = [((it.get("subtitle") or {}).get("label") or {}).get("text", "")
                             for it in sub.get("items", [])]
    return salida


def extraer_campos(html: str, estado: Optional[dict]) -> dict:
    soup = BeautifulSoup(html, "lxml")
    texto = (soup.body or soup).get_text("\n", strip=True)

    def buscar(patron):
        m = patron.search(texto)
        return m.group(1).strip() if m else None

    campos = {nombre: buscar(p) for nombre, p in PATRONES_TEXTO.items()}
    campos["superficie_total_m2"] = buscar(RE_SUPERFICIE_TOTAL)
    campos["superficie_util_m2"] = buscar(RE_SUPERFICIE_UTIL)
    campos["dormitorios"] = buscar(RE_DORMITORIOS)
    campos["banos"] = buscar(RE_BANOS)
    campos["gastos_comunes"] = buscar(RE_GASTOS_COMUNES) or buscar(RE_GASTOS_COMUNES_RESUMEN)
    # Texto crudo: la fecha absoluta se calcula en Silver restándolo a scraped_at, no a la fecha de hoy.
    campos["fecha_publicacion_texto"] = buscar(RE_FECHA_PUBLICACION)

    m_lat, m_lon = RE_LATITUD.search(html), RE_LONGITUD.search(html)
    m_mapa = RE_LATLON_MAPA.search(html)
    if m_lat and m_lon:
        campos["latitud"], campos["longitud"] = m_lat.group(1), m_lon.group(1)
    elif m_mapa:
        campos["latitud"], campos["longitud"] = m_mapa.group(1), m_mapa.group(2)
    else:
        campos["latitud"] = campos["longitud"] = None

    descripcion = None
    for sel in SELECTORES_DESCRIPCION:
        el = soup.select_one(sel)
        if el:
            descripcion = el.get_text("\n", strip=True)
            break
    campos["descripcion"] = descripcion
    campos["barrio"] = _buscar_clave(estado, "neighborhood") if estado else None
    campos["poi_crudo"] = extraer_poi_crudo(estado)
    return campos


# Plantilla de un corredor que reescribe la fecha sola ("...sigue disponible, fue publicada el 19 de Octubre."): sin esto, cada
# revisita contaba como cambio (~410 observaciones falsas en 3 días, P-29). Solo se quita para el hash; la descripción se guarda
# completa. Un aviso sin esa frase da el mismo hash que antes.
RE_FECHA_PLANTILLA = re.compile(r"fue publicada el \d{1,2} de [a-záéíóúñ]+", re.IGNORECASE)


def hash_observacion(obs: dict) -> str:
    estable = {k: v for k, v in obs.items() if k not in CAMPOS_VOLATILES}
    if isinstance(estable.get("descripcion"), str):
        estable["descripcion"] = RE_FECHA_PLANTILLA.sub("fue publicada el …", estable["descripcion"])
    return hashlib.sha256(json.dumps(estable, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


# ------------------------------------------------------------------ red

def visitar(url: str, id_aviso: str, referer: str) -> dict:
    """Devuelve {'resultado', 'detalle', 'http_status', 'url_final', 'html'}.
    Lanza Bloqueado ante CAPTCHA o muro de verificación (afecta a todo el sitio, no a este aviso)."""
    headers = {**config.HEADERS, "Referer": referer}
    base = {"http_status": None, "url_final": None, "html": None}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException as e:
        return {**base, "resultado": "error", "detalle": f"red: {e}"}

    base.update(http_status=resp.status_code, url_final=resp.url)
    if resp.status_code in (404, 410):
        return {**base, "resultado": "no_encontrado", "detalle": f"HTTP {resp.status_code}"}
    if resp.status_code in (403, 429):
        return {**base, "resultado": "bloqueado", "detalle": f"HTTP {resp.status_code}"}
    if resp.status_code != 200:
        return {**base, "resultado": "error", "detalle": f"HTTP {resp.status_code}"}
    if any(r in resp.url for r in RUTAS_MURO_VERIFICACION):
        return {**base, "resultado": "bloqueado", "detalle": f"muro de verificación: {resp.url}"}
    if "captcha" in resp.text.lower()[:8000]:
        return {**base, "resultado": "captcha", "detalle": "captcha"}

    soup = BeautifulSoup(resp.text, "lxml")
    canon = soup.find("link", attrs={"rel": "canonical"})
    og = soup.find("meta", attrs={"property": "og:url"})
    canonical = canon.get("href", "") if canon else ""
    og_url = og.get("content", "") if og else ""
    if id_aviso not in canonical or id_aviso not in og_url:
        # La grilla también lista proyectos inmobiliarios ("Desde $ X ... N unidades disponibles"): su URL
        # redirige a una página de proyecto cuyo canonical lleva otro ID numérico, y no es un aviso eliminado.
        if RE_CANONICAL_PROYECTO.search(canonical):
            return {**base, "resultado": "proyecto", "detalle": canonical}
        # Puede ser un aviso eliminado, pero también cualquier página anómala: no se concluye nada acá.
        return {**base, "resultado": "no_encontrado", "detalle": "la página no corresponde al aviso",
                "html": resp.text}
    # Una respuesta vacía nunca es éxito (P-25): el portal puede servir una versión reducida de la página, con status 200
    # y el aviso correcto, pero sin el estado de la aplicación (`appProps`) donde vienen precio, estado, barrio y puntos de
    # interés. Se toma como fallo: no se guarda como observación y, si se repite, frena la corrida como un bloqueo.
    if not _componentes(extraer_json_pagina(resp.text)):
        return {**base, "resultado": "error", "detalle": "página sin datos del aviso (sin appProps)"}
    return {**base, "resultado": "ok", "detalle": None, "html": resp.text,
            "canonical": canonical, "og_url": og_url}


# ------------------------------------------------------------------ cola y persistencia

# Ventana de las visitas sin precio ni estado (21-oct 14:42 a 22-oct 07:05, hora de Chile): ver P-25 en la bitácora.
SIN_PRECIO_DESDE = "2026-10-21 17:42:00+00"
SIN_PRECIO_HASTA = "2026-10-22 10:06:00+00"

SQL_COLA = """
-- Por comuna: una corrida de grilla que solo cubrió algunas comunas (o que quedó parcial) no debe hacer
-- parecer "desaparecidos" a los avisos de las demás.
WITH cob AS (SELECT comuna, max(run_id) AS rid FROM bronze.grilla_cobertura
             WHERE estado = 'completa' GROUP BY comuna),
ok AS (SELECT id_aviso, max(scraped_at) AS ult_ok FROM bronze.detalle_intentos
       WHERE resultado = 'ok' GROUP BY id_aviso),
fallos AS (SELECT i.id_aviso, count(*) AS n, max(i.scraped_at) AS ult_fallo
           FROM bronze.detalle_intentos i LEFT JOIN ok ON ok.id_aviso = i.id_aviso
           WHERE i.resultado IN ('error', 'no_encontrado') AND (ok.ult_ok IS NULL OR i.scraped_at > ok.ult_ok)
           GROUP BY i.id_aviso),
det AS (SELECT DISTINCT ON (id_aviso) id_aviso, estado_texto, precio_valor, scraped_at AS det_en,
               payload->>'fecha_publicacion_texto' AS txt_pub
        FROM bronze.detalle_avisos ORDER BY id_aviso, scraped_at DESC),
-- Edad de la publicación hoy: lo que decía el texto ("hace 13 días", "hace 2 meses", "esta semana", "hoy") cuando se
-- observó, más los días transcurridos desde esa observación.
edad AS (SELECT id_aviso,
                CASE WHEN txt_pub = 'hoy' THEN 0
                     WHEN txt_pub = 'esta semana' THEN 3
                     WHEN txt_pub ~ '^hace [0-9]+ d' THEN substring(txt_pub from '[0-9]+')::int
                     WHEN txt_pub ~ '^hace [0-9]+ mes' THEN substring(txt_pub from '[0-9]+')::int * 30
                     WHEN txt_pub ~ '^hace [0-9]+ a' THEN substring(txt_pub from '[0-9]+')::int * 365
                END + floor(extract(epoch FROM now() - det_en) / 86400)::int AS dias
         FROM det),
tramo AS (SELECT id_aviso,
                 CASE WHEN dias IS NULL OR dias <= 14 THEN %(r0)s WHEN dias <= 30 THEN %(r1)s
                      WHEN dias <= 60 THEN %(r2)s WHEN dias <= 120 THEN %(r3)s ELSE %(r4)s END AS interv
          FROM edad),
card AS (SELECT DISTINCT ON (id_aviso) id_aviso, comuna, tipo_propiedad, payload->>'url' AS url,
                scraped_at AS ult_card FROM bronze.grilla_avisos ORDER BY id_aviso, scraped_at DESC),
cola AS (
  SELECT gv.id_aviso, card.url, card.comuna, card.tipo_propiedad, ok.ult_ok,
         extract(epoch FROM now() - ok.ult_ok) / 86400.0 / tr.interv AS vencido,
         CASE
           WHEN ok.ult_ok IS NULL THEN 'nuevo'
           -- Reparación única (bitácora P-25): visitas hechas con el User-Agent que el portal respondía con una página sin
           -- precio ni estado. Se acota a esa ventana: al volver a visitarlas quedan fuera, y un aviso sin precio por otra
           -- causa no se revisita para siempre.
           WHEN det.precio_valor IS NULL AND det.estado_texto IS NULL
                AND det.det_en BETWEEN %(sp_desde)s AND %(sp_hasta)s THEN 'sin_precio'
           WHEN gv.ultimo_run_id < cob.rid AND ok.ult_ok < now() - make_interval(days => %(dias_desap)s)
                THEN 'desaparecido'
           WHEN card.ult_card > ok.ult_ok THEN 'tarjeta_cambio'
           WHEN ok.ult_ok < now() - make_interval(days => tr.interv) THEN 'rotacion'
         END AS motivo
  FROM bronze.grilla_vistos gv
  JOIN card ON card.id_aviso = gv.id_aviso
  LEFT JOIN cob ON cob.comuna = card.comuna
  LEFT JOIN ok ON ok.id_aviso = gv.id_aviso
  LEFT JOIN fallos f ON f.id_aviso = gv.id_aviso
  LEFT JOIN det ON det.id_aviso = gv.id_aviso
  LEFT JOIN tramo tr ON tr.id_aviso = gv.id_aviso
  WHERE card.url IS NOT NULL
    AND card.comuna = ANY(%(comunas)s)
    -- 'finalizado' es terminal: no se vuelve a visitar. Pausado sí, porque puede volver a publicarse.
    AND COALESCE(det.estado_texto, '') NOT ILIKE '%%finaliz%%'
    AND NOT EXISTS (SELECT 1 FROM bronze.detalle_intentos p
                    WHERE p.id_aviso = gv.id_aviso AND p.resultado = 'proyecto')
    AND COALESCE(f.n, 0) < %(max_fallos)s
    AND (f.ult_fallo IS NULL OR f.ult_fallo < now() - make_interval(hours => %(horas_reint)s))
)
SELECT id_aviso, url, comuna, tipo_propiedad, motivo FROM cola
WHERE motivo = ANY(%(motivos)s)
ORDER BY CASE motivo WHEN 'nuevo' THEN 1 WHEN 'sin_precio' THEN 2 WHEN 'desaparecido' THEN 3 WHEN 'tarjeta_cambio' THEN 4 ELSE 5 END,
         CASE WHEN motivo = 'rotacion' THEN -vencido ELSE 0 END,  -- en la rotación, primero el más atrasado respecto de su intervalo
         ult_ok NULLS FIRST, id_aviso DESC
LIMIT %(limite)s
"""


def obtener_cola(con, limite: int, motivos: list[str], comunas: list[str]) -> list[dict]:
    with con.cursor() as cur:
        cur.execute(SQL_COLA, {"dias_desap": DIAS_ENTRE_VISITAS_DESAPARECIDO,
                               **{f"r{i}": d for i, d in enumerate(DIAS_ROTACION_TRAMOS)},
                               "sp_desde": SIN_PRECIO_DESDE, "sp_hasta": SIN_PRECIO_HASTA,
                               "max_fallos": MAX_FALLOS_POR_AVISO, "horas_reint": HORAS_ENTRE_REINTENTOS,
                               "motivos": motivos, "comunas": comunas, "limite": limite})
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, fila)) for fila in cur.fetchall()]


def leer_factor_guardado() -> float:
    """Factor de pausa con que terminó la corrida anterior, si fue hace poco: la recuperación tras un 429 continúa entre
    tandas en vez de reiniciarse al ritmo base."""
    try:
        datos = json.loads(RUTA_RITMO.read_text(encoding="utf-8"))
        edad_h = (time.time() - float(datos["actualizado"])) / 3600
        return float(datos["factor"]) if edad_h <= VIGENCIA_RITMO_H else 1.0
    except (OSError, ValueError, KeyError):
        return 1.0


def guardar_factor(factor: float) -> None:
    try:
        RUTA_RITMO.write_text(json.dumps({"factor": factor, "actualizado": time.time()}), encoding="utf-8")
    except OSError:
        log.warning("No se pudo guardar el ritmo en %s", RUTA_RITMO.name)


def visitas_ultima_hora(con) -> int:
    with con.cursor() as cur:
        cur.execute("SELECT count(*) FROM bronze.detalle_intentos "
                    "WHERE scraped_at > now() - interval '1 hour' AND resultado <> 'bloqueado'")
        return cur.fetchone()[0]


def visitas_ultimas_24h(con) -> int:
    with con.cursor() as cur:
        cur.execute("SELECT count(*) FROM bronze.detalle_intentos "
                    "WHERE scraped_at > now() - interval '24 hours' AND resultado <> 'bloqueado'")
        return cur.fetchone()[0]


def registrar_intento(con, run_id, id_aviso, motivo, r: dict) -> None:
    with con, con.cursor() as cur:
        cur.execute(
            """INSERT INTO bronze.detalle_intentos
               (id_aviso, run_id, motivo_visita, resultado, detalle, http_status, url_final)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (id_aviso, run_id, motivo, r["resultado"], r.get("detalle"), r.get("http_status"), r.get("url_final")),
        )


def guardar_observacion(con, run_id: int, id_aviso: str, motivo: str, r: dict) -> bool:
    """Agrega una fila a detalle_avisos solo si lo observado cambió. Devuelve True si insertó."""
    estado = extraer_json_pagina(r["html"])
    comps = _componentes(estado)
    obs = {"estado_texto": extraer_estado_texto(comps), **extraer_precio(comps),
           "canonical": r["canonical"], "og_url": r["og_url"]}
    payload = extraer_campos(r["html"], estado)
    h = hash_observacion({**obs, **payload})

    with con, con.cursor() as cur:
        cur.execute("SELECT hash_payload FROM bronze.detalle_avisos WHERE id_aviso = %s "
                    "ORDER BY scraped_at DESC LIMIT 1", (id_aviso,))
        ultimo = cur.fetchone()
        if ultimo and ultimo[0] == h:
            return False

        ruta = config.RUTA_LANDING / "detalle" / date.today().isoformat() / f"{id_aviso}.html.gz"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(gzip.compress(r["html"].encode("utf-8")))
        html_path = str(ruta.relative_to(RAIZ)).replace("\\", "/")

        cur.execute(
            """INSERT INTO bronze.detalle_avisos
               (id_aviso, run_id, motivo_visita, estado_texto, precio_valor, precio_moneda, precio_original,
                canonical, og_url, html_path, hash_payload, payload)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (id_aviso, run_id, motivo, obs["estado_texto"], obs["precio_valor"], obs["precio_moneda"],
             obs["precio_original"], obs["canonical"], obs["og_url"], html_path, h, Json(payload)),
        )
    return True


def iniciar_run(con) -> int:
    with con, con.cursor() as cur:
        cur.execute("INSERT INTO bronze.runs (fuente) VALUES ('detalle') RETURNING run_id")
        return cur.fetchone()[0]


def cerrar_run(con, run_id, estado, visitas, filas, detalle) -> None:
    with con, con.cursor() as cur:
        cur.execute("UPDATE bronze.runs SET fin=now(), estado=%s, paginas=%s, filas_nuevas=%s, detalle=%s "
                    "WHERE run_id=%s", (estado, visitas, filas, detalle, run_id))


# ------------------------------------------------------------------ corrida

def ejecutar(db: ConexionResiliente, limite: int, motivos: list[str], comunas: list[str],
             presupuesto: int = PRESUPUESTO_24H, factor_inicial: float = 1.0) -> tuple[str, int]:
    """`db` reabre la conexión si el servidor la corta (por ejemplo, al suspender el equipo)."""
    hechas = db.ejecutar(visitas_ultimas_24h)
    disponible = max(presupuesto - hechas, 0)
    log.info("Presupuesto 24 h: %d de %d usadas, quedan %d", hechas, presupuesto, disponible)
    if disponible < min(MIN_VISITAS_TANDA, limite):
        log.info("Presupuesto de 24 h agotado (quedan %d, el mínimo por tanda es %d): no se visita nada",
                 disponible, min(MIN_VISITAS_TANDA, limite))
        return "presupuesto", 0
    cola = db.ejecutar(obtener_cola, min(limite, disponible), motivos, comunas)
    por_motivo = {m: sum(1 for c in cola if c["motivo"] == m) for m in motivos}
    log.info("Cola: %d avisos %s", len(cola), por_motivo)
    if not cola:
        return "vacia", 0

    run_id = db.ejecutar(iniciar_run)
    visitas = filas = fallos_seguidos = fallidas = 0
    bloqueos = bloqueos_seguidos = visitas_desde_bloqueo = 0
    aguantes: list[int] = []
    factor = max(1.0, min(max(factor_inicial, leer_factor_guardado()), FACTOR_PAUSA_MAX))
    if factor > 1:
        log.info("Se retoma con las pausas en x%.0f (la corrida anterior terminó recuperándose de un bloqueo)", factor)
    t_inicio = time.monotonic()
    estado, detalle = "success", None
    try:
        i = 0
        while i < len(cola):
            item = cola[i]
            referer = f"{config.BASE_URL}/{config.OPERACION}/{item['tipo_propiedad']}/{item['comuna']}"
            try:
                r = visitar(item["url"], item["id_aviso"], referer)
                db.ejecutar(registrar_intento, run_id, item["id_aviso"], item["motivo"], r)

                if r["resultado"] in ("captcha", "bloqueado"):
                    raise Bloqueado(f"{r['resultado']}: {r['detalle']}")
                if r["resultado"] == "ok":
                    fallos_seguidos = 0
                    if db.ejecutar(guardar_observacion, run_id, item["id_aviso"], item["motivo"], r):
                        filas += 1
                elif r["resultado"] == "proyecto":
                    fallos_seguidos = 0  # respuesta válida del sitio: no es señal de bloqueo
                    log.info("%s es un proyecto inmobiliario (%s)", item["id_aviso"], r["detalle"])
                else:
                    fallos_seguidos += 1
                    fallidas += 1
                    log.warning("%s: %s (%s)", item["id_aviso"], r["resultado"], r["detalle"])
                    # Varios fallos seguidos suelen ser el sitio bloqueándonos, no avisos eliminados.
                    if fallos_seguidos >= MAX_FALLOS_SEGUIDOS_EN_CORRIDA:
                        raise Bloqueado(f"{fallos_seguidos} fallos consecutivos")
            except Bloqueado as e:
                bloqueos += 1
                bloqueos_seguidos += 1
                aguantes.append(visitas_desde_bloqueo)
                if bloqueos_seguidos >= MAX_BLOQUEOS_SEGUIDOS:
                    raise
                factor = min(factor * 2, FACTOR_PAUSA_MAX)
                en_hora, en_24h = db.ejecutar(visitas_ultima_hora), db.ejecutar(visitas_ultimas_24h)
                log.warning("BLOQUEO %d (%s): aguantó %d visitas desde el anterior (última hora %d, 24 h %d); espera %d min "
                            "y baja el ritmo (pausas x%.0f)", bloqueos, e, visitas_desde_bloqueo, en_hora, en_24h,
                            ESPERA_BLOQUEO_S // 60, factor)
                visitas_desde_bloqueo = fallos_seguidos = 0
                guardar_factor(factor)
                time.sleep(ESPERA_BLOQUEO_S)
                continue  # reintenta el mismo aviso
            visitas += 1
            visitas_desde_bloqueo += 1
            bloqueos_seguidos = 0
            # Cuando el sitio deja de bloquear (por ejemplo, al pasar las 24 h), las pausas vuelven a las originales por etapas.
            if factor > 1 and visitas_desde_bloqueo % VISITAS_PARA_RELAJAR == 0:
                factor = max(1.0, factor / 2)
                log.info("%d visitas buenas seguidas: las pausas bajan a x%.0f", visitas_desde_bloqueo, factor)
                guardar_factor(factor)
            i += 1
            if visitas % CADA_N_VISITAS_AVANCE == 0:
                minutos = (time.monotonic() - t_inicio) / 60
                ritmo = visitas / minutos if minutos else 0.0
                resta = (len(cola) - visitas) / ritmo if ritmo else float("inf")
                log.info("Avance: %d/%d (%.0f %%) | %.1f visitas/min | observaciones nuevas %d | sin leer %d | "
                         "bloqueos %d | resta ~%d h %02d min", visitas, len(cola), 100 * visitas / len(cola), ritmo,
                         filas, fallidas, bloqueos, resta // 60, resta % 60)
            time.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX) * factor)
    except Bloqueado as e:
        estado, detalle = "bloqueado", f"{e}; aguantes entre bloqueos: {aguantes}"
        log.error("ABORTADO: %s", detalle)
    except Exception as e:  # noqa: BLE001 - se registra en runs y se relanza
        db.ejecutar(cerrar_run, run_id, "error", visitas, filas, repr(e))
        raise
    if estado == "success" and bloqueos:
        detalle = f"{bloqueos} bloqueos superados; visitas entre bloqueos: {aguantes}"
    guardar_factor(factor)
    db.ejecutar(cerrar_run, run_id, estado, visitas, filas, detalle)
    log.info("Fin: estado=%s, visitas=%d, observaciones nuevas=%d, bloqueos=%d", estado, visitas, filas, bloqueos)
    return estado, visitas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limite", type=int, default=300, help="máximo de avisos a visitar en esta corrida")
    ap.add_argument("--motivos", nargs="+", default=["nuevo", "sin_precio", "desaparecido", "tarjeta_cambio", "rotacion"])
    ap.add_argument("--comunas", nargs="+", default=config.COMUNAS_RM, help="solo avisos de estas comunas")
    ap.add_argument("--factor-pausa", type=float, default=1.0,
                    help="multiplicador inicial de las pausas; baja solo tras visitas buenas seguidas")
    ap.add_argument("--presupuesto-dia", type=int, default=PRESUPUESTO_24H,
                    help="visitas máximas en una ventana móvil de 24 h (cuenta todas las corridas)")
    args = ap.parse_args()
    db = ConexionResiliente("BD_STRING_SCRAPER")
    try:
        estado, _ = ejecutar(db, args.limite, args.motivos, args.comunas, args.presupuesto_dia, args.factor_pausa)
    finally:
        db.close()
    return CODIGOS_SALIDA.get(estado, 1)


if __name__ == "__main__":
    sys.exit(main())
