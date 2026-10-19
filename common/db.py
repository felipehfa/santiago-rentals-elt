"""Conexión a Supabase. Las cadenas se leen de .env (local, fuera de git) o del entorno.

BD_STRING es la del rol dueño (Silver, Gold, migraciones, cargas únicas). Los scrapers usan la de su rol de
mínimo privilegio (scraper_local), BD_STRING_SCRAPER; si no existe todavía, caen a
BD_STRING con un aviso, para no frenar la transición.
"""
import logging
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
log = logging.getLogger(__name__)


def conectar(variable: str = "BD_STRING") -> "psycopg2.extensions.connection":
    """Devuelve una conexión nueva; el caller es dueño de ella y la cierra."""
    load_dotenv(RAIZ / ".env")
    bd_string = os.environ.get(variable)
    if not bd_string and variable != "BD_STRING":
        log.warning("Falta %s: se usa BD_STRING (rol dueño). Crear el rol de mínimo privilegio y definirla.", variable)
        bd_string = os.environ.get("BD_STRING")
    if not bd_string:
        raise RuntimeError(f"Falta {variable} (definirla en .env)")
    return psycopg2.connect(bd_string, connect_timeout=15)
