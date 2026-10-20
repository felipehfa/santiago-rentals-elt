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

# Pausa entre peticiones (s). El orquestador la sube con estas variables de entorno para no cargar el sitio.
DELAY_MIN = float(os.environ.get("PAUSA_MIN_S", 3.0))
DELAY_MAX = float(os.environ.get("PAUSA_MAX_S", 7.0))

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
