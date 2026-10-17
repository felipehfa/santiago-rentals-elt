"""Configuración compartida del scraper. Las comunas viven acá, no en el código de los scrapers,
para poder ampliar la cobertura sin tocar lógica."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

BASE_URL = "https://www.portalinmobiliario.com"
OPERACION = "arriendo"
TIPOS_PROPIEDAD = ["departamento"]
RESULTADOS_POR_PAGINA = 48  # tamaño real de página del sitio

# Slugs en formato "comuna-metropolitana". Verificados con scripts/spike_slugs.py (todos responden 200).
# Oleada 1 = núcleo; oleada 2 = segundo anillo; oleada 3 = reserva. Se scrapean todas.
COMUNAS_RM = [
    # oleada 1
    "santiago-metropolitana", "nunoa-metropolitana", "providencia-metropolitana",
    "las-condes-metropolitana", "vitacura-metropolitana", "estacion-central-metropolitana",
    "san-miguel-metropolitana", "independencia-metropolitana", "macul-metropolitana",
    # oleada 2
    "la-florida-metropolitana", "la-reina-metropolitana", "lo-barnechea-metropolitana",
    "recoleta-metropolitana", "quilicura-metropolitana", "maipu-metropolitana",
    # oleada 3 (reserva)
    "puente-alto-metropolitana", "san-bernardo-metropolitana", "penalolen-metropolitana",
    "huechuraba-metropolitana", "quinta-normal-metropolitana", "conchali-metropolitana",
    "cerrillos-metropolitana", "pedro-aguirre-cerda-metropolitana",
]

DELAY_MIN = 3.0
DELAY_MAX = 7.0

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
