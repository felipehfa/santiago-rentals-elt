"""Orquestador: alterna el detalle y la grilla sin intervención, respetando los bloqueos (429) del sitio.

Ciclo:  detalle -> grilla -> detalle -> grilla ...

  - Detalle: recorre su cola (nuevos, desaparecidos, tarjeta cambiada, rotación) dentro del presupuesto de 24 h. Ante un
    429 espera y baja el ritmo por su cuenta; solo termina bloqueado si varios bloqueos seguidos no lo dejan avanzar.
    Si queda bloqueado, el orquestador espera (la espera crece en cada intento) y vuelve a lanzarlo.
  - Grilla: busca avisos nuevos y cambios en las comunas de config.COMUNAS_RM. Si el sitio la bloquea a mitad de camino,
    espera y reanuda solo con las comunas que faltaban en esa corrida, sin repetir las ya completas.
  - La grilla corre como máximo cada `--grilla-cada-horas`, para no cargar el sitio con ~230 páginas seguidas.
  - Si el presupuesto de visitas se agota, espera a que se libere.

Presupuesto: `--presupuesto-dia` (2.000 por defecto, lo que pide revisar cada aviso una vez por semana).
Pausa entre peticiones: `--pausa-min`/`--pausa-max` (6 y 12 s por defecto) se pasan a los dos scrapers.
Para detenerlo con calma, crear el archivo `logs/orquestador.stop` (termina el paso en curso y sale).
Registro: `logs/orquestador.log` (fijo, fuera de git).

Uso:
    python bronze/orquestador.py
    python bronze/orquestador.py --grilla-cada-horas 12 --max-ciclos 2
"""
import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import config  # noqa: E402
from common.db import ConexionResiliente  # noqa: E402

RUTA_LOG = RAIZ / "logs" / "orquestador.log"
RUTA_STOP = RAIZ / "logs" / "orquestador.stop"
RUTA_LOG.parent.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(RUTA_LOG, encoding="utf-8")])
log = logging.getLogger("orquestador")

ESPERA_DETALLE_BLOQUEADO_S = (30 * 60, 60 * 60, 120 * 60)  # crece con cada intento seguido; la última se repite
ESPERA_GRILLA_BLOQUEADA_S = (30 * 60, 60 * 60, 120 * 60)
ESPERA_PRESUPUESTO_S = 30 * 60
ESPERA_GRILLA_FALLIDA_S = 2 * 60 * 60  # tras agotar las reanudaciones, antes de volver a intentar la grilla
MAX_REINTENTOS_GRILLA = 6   # reanudaciones seguidas de una misma grilla antes de dejarla para el próximo ciclo

COD_DETALLE_PRESUPUESTO = 4  # ver CODIGOS_SALIDA en scraper_detalle.py


def hay_orden_de_parar() -> bool:
    if RUTA_STOP.exists():
        log.info("Se encontró %s: el orquestador termina.", RUTA_STOP.name)
        return True
    return False


def esperar(segundos: int, motivo: str) -> bool:
    """Duerme en tramos cortos para poder atender la orden de parar. Devuelve False si hay que terminar."""
    hasta = datetime.now() + timedelta(seconds=segundos)
    log.info("Espera %d min (%s); retoma a las %s", segundos // 60, motivo, hasta.strftime("%H:%M"))
    while datetime.now() < hasta:
        if hay_orden_de_parar():
            return False
        time.sleep(min(30, max((hasta - datetime.now()).total_seconds(), 0)))
    return True


def correr(script: str, *args: str, pausa: tuple[float, float]) -> int:
    entorno = {**os.environ, "PYTHONPATH": str(RAIZ), "PAUSA_MIN_S": str(pausa[0]), "PAUSA_MAX_S": str(pausa[1])}
    comando = [sys.executable, str(RAIZ / "bronze" / script), *args]
    log.info("Lanza %s %s", script, " ".join(args))
    return subprocess.run(comando, cwd=RAIZ, env=entorno, check=False).returncode


# ------------------------------------------------------------------ consultas a la base

def ultima_grilla(db: ConexionResiliente) -> tuple[int, str] | None:
    def consulta(con):
        with con.cursor() as cur:
            cur.execute("SELECT run_id, estado FROM bronze.runs WHERE fuente = 'grilla' ORDER BY run_id DESC LIMIT 1")
            return cur.fetchone()
    return db.ejecutar(consulta)


def ultima_grilla_buena(db: ConexionResiliente) -> datetime | None:
    """Inicio de la última grilla que recorrió todas las comunas pedidas (success o parcial)."""
    def consulta(con):
        with con.cursor() as cur:
            cur.execute("SELECT max(inicio) FROM bronze.runs WHERE fuente = 'grilla' AND estado IN ('success', 'parcial')")
            return cur.fetchone()[0]
    return db.ejecutar(consulta)


def comunas_cubiertas(db: ConexionResiliente, run_id: int) -> set[str]:
    def consulta(con):
        with con.cursor() as cur:
            cur.execute("SELECT DISTINCT comuna FROM bronze.grilla_cobertura WHERE run_id = %s", (run_id,))
            return {f[0] for f in cur.fetchall()}
    return db.ejecutar(consulta)


# ------------------------------------------------------------------ pasos

def paso_detalle(pausa, presupuesto: int) -> str:
    """Corre el detalle hasta vaciar su cola. Devuelve 'listo', 'presupuesto' o 'parar'."""
    intento = 0
    while True:
        codigo = correr("scraper_detalle.py", "--limite", "20000", "--presupuesto-dia", str(presupuesto), pausa=pausa)
        if codigo == 0:
            return "listo"
        if codigo == COD_DETALLE_PRESUPUESTO:
            return "presupuesto"
        if hay_orden_de_parar():
            return "parar"
        espera = ESPERA_DETALLE_BLOQUEADO_S[min(intento, len(ESPERA_DETALLE_BLOQUEADO_S) - 1)]
        intento += 1
        log.warning("El detalle terminó con código %d (bloqueado o con error); reintento %d", codigo, intento)
        if not esperar(espera, "el detalle quedó bloqueado"):
            return "parar"


def paso_grilla(db, pausa) -> str:
    """Corre la grilla; si el sitio la bloquea, reanuda solo con las comunas que faltaban. 'listo' | 'fallo' | 'parar'."""
    pendientes = list(config.COMUNAS_RM)
    for intento in range(MAX_REINTENTOS_GRILLA + 1):
        codigo = correr("scraper_grilla.py", "--comunas", *pendientes, pausa=pausa)
        corrida = ultima_grilla(db)
        if corrida is None:
            return "fallo"
        run_id, estado = corrida
        if estado in ("success", "parcial"):
            log.info("Grilla terminada (%s, código %d)", estado, codigo)
            return "listo"
        if hay_orden_de_parar():
            return "parar"
        hechas = comunas_cubiertas(db, run_id)
        pendientes = [c for c in pendientes if c not in hechas]
        if not pendientes:
            return "listo"
        if intento == MAX_REINTENTOS_GRILLA:
            break
        log.warning("La grilla quedó %s con %d comunas pendientes (%s...)", estado, len(pendientes),
                    ", ".join(c.removesuffix("-metropolitana") for c in pendientes[:3]))
        espera = ESPERA_GRILLA_BLOQUEADA_S[min(intento, len(ESPERA_GRILLA_BLOQUEADA_S) - 1)]
        if not esperar(espera, "la grilla fue bloqueada"):
            return "parar"
    log.error("La grilla no pudo completarse tras %d reanudaciones; se sigue con el detalle", MAX_REINTENTOS_GRILLA)
    return "fallo"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grilla-cada-horas", type=float, default=6.0, help="separación mínima entre dos grillas")
    ap.add_argument("--presupuesto-dia", type=int, default=2000, help="visitas de detalle por ventana móvil de 24 h")
    ap.add_argument("--pausa-min", type=float, default=6.0)
    ap.add_argument("--pausa-max", type=float, default=12.0)
    ap.add_argument("--max-ciclos", type=int, default=0, help="0 = sin límite")
    args = ap.parse_args()
    pausa = (args.pausa_min, args.pausa_max)
    if RUTA_STOP.exists():
        RUTA_STOP.unlink()  # una orden vieja no debe impedir esta corrida

    db = ConexionResiliente("BD_STRING_SCRAPER")
    ciclos = 0
    try:
        log.info("INICIO orquestador | %d comunas | pausas %.0f-%.0f s | grilla cada %.0f h", len(config.COMUNAS_RM),
                 *pausa, args.grilla_cada_horas)
        while not hay_orden_de_parar():
            resultado = paso_detalle(pausa, args.presupuesto_dia)
            if resultado == "parar":
                break
            if resultado == "presupuesto":
                log.info("Presupuesto de visitas agotado")

            ultima = ultima_grilla_buena(db)
            hace_h = (datetime.now(ultima.tzinfo) - ultima).total_seconds() / 3600 if ultima else float("inf")
            if hace_h >= args.grilla_cada_horas:
                resultado_grilla = paso_grilla(db, pausa)
                if resultado_grilla == "parar":
                    break
                if resultado_grilla == "fallo" and not esperar(ESPERA_GRILLA_FALLIDA_S, "la grilla no se pudo completar"):
                    break
            elif resultado == "presupuesto":
                if not esperar(ESPERA_PRESUPUESTO_S, "esperando que se libere el presupuesto"):
                    break
                continue
            else:
                faltan = args.grilla_cada_horas - hace_h
                if not esperar(int(faltan * 3600), "todavía no toca la grilla"):
                    break
                continue

            ciclos += 1
            if args.max_ciclos and ciclos >= args.max_ciclos:
                log.info("Se completaron %d ciclos", ciclos)
                break
    finally:
        db.close()
    log.info("FIN orquestador | ciclos completos: %d", ciclos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
