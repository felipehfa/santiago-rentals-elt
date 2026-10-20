"""Conexión a Supabase. Las cadenas se leen de .env (local, fuera de git) o del entorno.

BD_STRING es la del rol dueño (Silver, Gold, migraciones, cargas únicas). Los scrapers usan la de su rol de
mínimo privilegio (scraper_local), BD_STRING_SCRAPER; si no existe todavía, caen a
BD_STRING con un aviso, para no frenar la transición.
"""
import contextlib
import logging
import os
import time
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


class ConexionResiliente:
    """Conexión que se reabre si el servidor la corta (por ejemplo, al suspender el equipo o por un corte de red).

    `ejecutar(fn, *args)` llama a `fn(con, *args)`; si la conexión se perdió, reconecta y repite la operación. Las
    operaciones deben poder repetirse sin daño: o fallan antes de confirmar (la transacción se pierde con la
    conexión) o son idempotentes. Si no logra reconectar tras varios intentos espaciados, relanza el error."""

    ESPERAS_RECONEXION_S = (5, 15, 45, 90, 180)  # tras reanudar un equipo, la red puede tardar en volver

    def __init__(self, variable: str = "BD_STRING"):
        self.variable = variable
        self.con = conectar(variable)

    def ejecutar(self, fn, *args):
        try:
            return fn(self.con, *args)
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            log.warning("Conexión a la base perdida (%s); reconectando", type(e).__name__)
            self._reconectar()
            return fn(self.con, *args)

    def _reconectar(self) -> None:
        with contextlib.suppress(Exception):  # ya estaba rota
            self.con.close()
        for i, espera in enumerate(self.ESPERAS_RECONEXION_S, start=1):
            try:
                self.con = conectar(self.variable)
                log.info("Reconectado a la base (intento %d)", i)
                return
            except psycopg2.Error as e:  # el mensaje puede traer parte de la cadena: solo se informa la clase
                log.warning("Reconexión %d fallida (%s); reintento en %d s", i, type(e).__name__, espera)
                time.sleep(espera)
        self.con = conectar(self.variable)  # último intento: si falla, el error sube y la corrida se cierra

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.con.close()
