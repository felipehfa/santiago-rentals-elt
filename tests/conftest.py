"""Los scrapers viven en bronze/ y usan imports planos (`import config`, `from common.db import ...`)."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
for ruta in (RAIZ, RAIZ / "bronze"):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))
