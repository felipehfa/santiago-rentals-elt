"""Configuración compartida del scraper. Las comunas viven acá, no en el código de los scrapers,
para poder ampliar la cobertura sin tocar lógica."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

BASE_URL = "https://www.portalinmobiliario.com"
OPERACION = "arriendo"
TIPOS_PROPIEDAD = ["departamento"]
RESULTADOS_POR_PAGINA = 48  # tamaño real de página del sitio

# Slugs en formato "comuna-metropolitana". Verificados con scripts/spike_slugs.py (todos responden 200).
# Solo las comunas centrales o de interés. Quedaron fuera (2026-10-19): Las Condes, Vitacura, Lo Barnechea, La Reina,
# Peñalolén, Quilicura, Maipú, Puente Alto, San Bernardo, Cerrillos y Pedro Aguirre Cerda. Sus avisos ya cargados
# siguen en Bronce; para volver a scrapearlas basta agregar el slug acá.
COMUNAS_RM = [
    "santiago-metropolitana", "nunoa-metropolitana", "providencia-metropolitana",
    "estacion-central-metropolitana", "san-miguel-metropolitana", "independencia-metropolitana",
    "macul-metropolitana", "la-florida-metropolitana", "recoleta-metropolitana",
    "huechuraba-metropolitana", "quinta-normal-metropolitana", "conchali-metropolitana",
]

# Código de comuna (INE) de cada slug. La asignación de unidad vecinal solo usa los polígonos de las comunas que se scrapean.
CODIGOS_COMUNA = {
    "santiago-metropolitana": 13101, "cerrillos-metropolitana": 13102, "conchali-metropolitana": 13104,
    "estacion-central-metropolitana": 13106, "huechuraba-metropolitana": 13107, "independencia-metropolitana": 13108,
    "la-florida-metropolitana": 13110, "lo-barnechea-metropolitana": 13113, "las-condes-metropolitana": 13114,
    "la-reina-metropolitana": 13115, "macul-metropolitana": 13118, "maipu-metropolitana": 13119,
    "nunoa-metropolitana": 13120, "pedro-aguirre-cerda-metropolitana": 13121, "penalolen-metropolitana": 13122,
    "providencia-metropolitana": 13123, "quilicura-metropolitana": 13125, "quinta-normal-metropolitana": 13126,
    "recoleta-metropolitana": 13127, "san-miguel-metropolitana": 13130, "vitacura-metropolitana": 13132,
    "puente-alto-metropolitana": 13201, "san-bernardo-metropolitana": 13401,
}
COD_COM_ALCANCE = sorted(CODIGOS_COMUNA[c] for c in COMUNAS_RM)

# Pausa entre peticiones (s). El orquestador la sube con estas variables de entorno para no cargar el sitio.
DELAY_MIN = float(os.environ.get("PAUSA_MIN_S", 3.0))
DELAY_MAX = float(os.environ.get("PAUSA_MAX_S", 7.0))

# El scraper se identifica y deja un contacto (proyecto personal, sin fines comerciales). Antes usaba el User-Agent de un
# Chrome; si el sitio rechaza este, hay que decidirlo a conciencia y no volver a disfrazarse sin más.
USER_AGENT = (
    "santiago-rentals-research/1.0 (proyecto personal sin fines comerciales; "
    "contacto: https://github.com/felipehfa , https://www.linkedin.com/in/felipehfa/)"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# HTML crudo (capa landing). Local, fuera de git.
RUTA_LANDING = RAIZ / "landing"
