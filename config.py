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
# Peñalolén, Quilicura, Maipú, Puente Alto, San Bernardo, Cerrillos y Pedro Aguirre Cerda. Sus avisos se borraron de
# la base y de landing/ el 2026-10-24 (bitácora P-28); para volver a scrapearlas basta agregar el slug acá (parten de cero).
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

# User-Agent de navegador. Se probó uno que se identificaba (nombre del proyecto y contacto) el 21-oct-2026: el portal respondió
# 200 pero con una versión reducida de la página, sin precio ni estado (bitácora P-25), y el usuario pidió volver a este.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# HTML crudo (capa landing). Local, fuera de git.
RUTA_LANDING = RAIZ / "landing"
