"""Conexión a Supabase. BD_STRING se lee de .env (local, fuera de git) o del entorno."""
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]


def conectar() -> "psycopg2.extensions.connection":
    """Devuelve una conexión nueva; el caller es dueño de ella y la cierra."""
    load_dotenv(RAIZ / ".env")
    bd_string = os.environ.get("BD_STRING")
    if not bd_string:
        raise RuntimeError("Falta BD_STRING (definirla en .env, ver .env.example)")
    return psycopg2.connect(bd_string, connect_timeout=15)
