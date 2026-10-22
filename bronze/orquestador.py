"""Orquestador: alterna el detalle y la grilla sin intervención, respetando los bloqueos (429) del sitio.

Ciclo:  tanda de detalle -> (si toca, grilla) -> tanda de detalle -> ...

  - Detalle: recorre su cola (nuevos, desaparecidos, tarjeta cambiada, rotación) dentro del presupuesto de 24 h. Ante un
    429 espera y baja el ritmo por su cuenta; solo termina bloqueado si varios bloqueos seguidos no lo dejan avanzar.
    Si queda bloqueado, el orquestador espera (la espera crece en cada intento) y vuelve a lanzarlo.
  - Grilla: busca avisos nuevos y cambios en las comunas de config.COMUNAS_RM. Si el sitio la bloquea a mitad de camino,
    espera y reanuda solo con las comunas que faltaban en esa corrida, sin repetir las ya completas.
  - Silver y Gold: cada `--silver-gold-cada-horas` (1 por defecto) se reconstruyen desde Bronce, entre tandas y también
    mientras corre una tanda de detalle (que puede pasar horas esperando por 429); nunca durante una grilla. Si fallan, se reintenta a los 30 minutos. Estado: `logs/silver_gold.json`.
  - La grilla corre como máximo cada `--grilla-cada-horas`, para no cargar el sitio con ~230 páginas seguidas.
  - Si el presupuesto de visitas se agota, espera a que se libere.

Presupuesto: `--presupuesto-dia` (5.000 por defecto: el primer 429 del sitio llegó con ~7.500 visitas en 24 h, y no se busca más ese límite).
Pausa entre peticiones: `--pausa-min`/`--pausa-max` (6 y 12 s por defecto) se pasan a los dos scrapers.
Para detenerlo con calma, crear el archivo `logs/orquestador.stop` (termina el paso en curso y sale).
Registro: `logs/orquestador.log` (fijo, fuera de git).

Uso:
    python bronze/orquestador.py
    python bronze/orquestador.py --grilla-cada-horas 12 --max-ciclos 2
"""
import argparse
import json
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
RUTA_SILVER_GOLD = RAIZ / "logs" / "silver_gold.json"
RUTA_LOG.parent.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(RUTA_LOG, encoding="utf-8")])
log = logging.getLogger("orquestador")

ESPERA_DETALLE_BLOQUEADO_S = (30 * 60, 60 * 60, 120 * 60)  # crece con cada intento seguido; la última se repite
ESPERA_GRILLA_BLOQUEADA_S = (30 * 60, 60 * 60, 120 * 60)
ESPERA_SIN_TRABAJO_S = 30 * 60  # sin nada que visitar o sin presupuesto: se revisa de nuevo cada tanto
ESPERA_GRILLA_FALLIDA_S = 2 * 60 * 60  # tras agotar las reanudaciones, antes de volver a intentar la grilla
REINTENTO_SILVER_GOLD_S = 30 * 60  # tras un fallo de Silver o Gold
# Cada cuánto se revisa, mientras corre una tanda de detalle, si toca reconstruir Silver y Gold. Una tanda puede pasar horas
# esperando por 429 seguidos y Gold no debe quedar atrasado por eso (P-26).
REVISION_DURANTE_DETALLE_S = 60
MAX_REINTENTOS_GRILLA = 6   # reanudaciones seguidas de una misma grilla antes de dejarla para el próximo ciclo

COD_DETALLE_PRESUPUESTO, COD_DETALLE_VACIA = 4, 5  # ver CODIGOS_SALIDA en scraper_detalle.py


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


def esperar_proceso(proc, durante=None, cada_s: float = REVISION_DURANTE_DETALLE_S) -> int:
    """Espera a que termine `proc` y, mientras tanto, llama a `durante()` cada `cada_s` segundos."""
    while proc.poll() is None:
        if durante is not None:
            durante()
        if proc.poll() is None:
            time.sleep(cada_s)
    return proc.returncode


def correr(script: str, *args: str, pausa: tuple[float, float], durante=None) -> int:
    """Lanza un scraper y espera a que termine. `durante` (opcional) se llama a intervalos mientras corre."""
    entorno = {**os.environ, "PYTHONPATH": str(RAIZ), "PAUSA_MIN_S": str(pausa[0]), "PAUSA_MAX_S": str(pausa[1])}
    comando = [sys.executable, str(RAIZ / "bronze" / script), *args]
    log.info("Lanza %s %s", script, " ".join(args))
    return esperar_proceso(subprocess.Popen(comando, cwd=RAIZ, env=entorno), durante)


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

def paso_detalle(pausa, presupuesto: int, factor: float, tanda: int, silver_gold_cada_horas: float = 1.0) -> str:
    """Corre una tanda del detalle (hasta `tanda` visitas). Devuelve 'listo' (puede quedar más cola), 'vacia' (no había
    nada que visitar), 'presupuesto' (agotado) o 'parar'. Las tandas cortas dejan a la grilla entrar a su hora.
    Mientras la tanda corre (incluidas sus esperas por 429), Silver y Gold se siguen reconstruyendo a su hora: leen Bronce
    con una instantánea fija (REPEATABLE READ), así que las visitas en curso no los dejan inconsistentes."""
    def silver_gold_a_su_hora():
        if toca_silver_gold(silver_gold_cada_horas):
            paso_silver_gold()

    intento = 0
    while True:
        codigo = correr("scraper_detalle.py", "--limite", str(tanda), "--presupuesto-dia", str(presupuesto),
                        "--factor-pausa", str(factor), pausa=pausa, durante=silver_gold_a_su_hora)
        if codigo == 0:
            return "listo"
        if codigo == COD_DETALLE_VACIA:
            return "vacia"
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


def leer_estado_silver_gold() -> dict:
    try:
        return json.loads(RUTA_SILVER_GOLD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def toca_silver_gold(cada_horas: float) -> bool:
    """True si pasó el intervalo desde la última reconstrucción buena (o 30 min desde el último intento fallido)."""
    estado = leer_estado_silver_gold()
    ahora = datetime.now()
    try:
        if estado.get("fallo") and (ahora - datetime.fromisoformat(estado["fallo"])).total_seconds() < REINTENTO_SILVER_GOLD_S:
            return False
        return (ahora - datetime.fromisoformat(estado["ok"])).total_seconds() >= cada_horas * 3600
    except (KeyError, ValueError):
        return True


def paso_silver_gold() -> bool:
    """Reconstruye Silver y luego Gold (corren con BD_STRING, el dueño). Registra el resultado en el archivo de estado."""
    estado = leer_estado_silver_gold()
    for script in ("silver/construir_silver.py", "gold/construir_gold.py"):
        entorno = {**os.environ, "PYTHONPATH": str(RAIZ)}
        log.info("Lanza %s", script)
        if subprocess.run([sys.executable, str(RAIZ / script)], cwd=RAIZ, env=entorno, check=False).returncode != 0:
            log.error("%s falló; Silver y Gold se reintentan en %d min", script, REINTENTO_SILVER_GOLD_S // 60)
            estado["fallo"] = datetime.now().isoformat(timespec="seconds")
            RUTA_SILVER_GOLD.write_text(json.dumps(estado), encoding="utf-8")
            return False
    RUTA_SILVER_GOLD.write_text(json.dumps({"ok": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    log.info("Silver y Gold reconstruidos")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grilla-cada-horas", type=float, default=6.0, help="separación mínima entre dos grillas")
    ap.add_argument("--silver-gold-cada-horas", type=float, default=1.0, help="separación entre reconstrucciones de Silver y Gold")
    ap.add_argument("--presupuesto-dia", type=int, default=5000, help="visitas de detalle por ventana móvil de 24 h")
    ap.add_argument("--factor-pausa", type=float, default=1.0,
                    help="multiplicador inicial de las pausas del detalle (baja solo con visitas buenas seguidas)")
    ap.add_argument("--pausa-min", type=float, default=6.0)
    ap.add_argument("--pausa-max", type=float, default=12.0)
    ap.add_argument("--tanda", type=int, default=400, help="visitas de detalle por tanda; entre tandas se revisa si toca la grilla")
    ap.add_argument("--max-ciclos", type=int, default=0, help="0 = sin límite (cuenta grillas completadas)")
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
            resultado = paso_detalle(pausa, args.presupuesto_dia, args.factor_pausa, args.tanda, args.silver_gold_cada_horas)
            if resultado == "parar":
                break

            if toca_silver_gold(args.silver_gold_cada_horas):
                paso_silver_gold()
                if hay_orden_de_parar():
                    break

            ultima = ultima_grilla_buena(db)
            hace_h = (datetime.now(ultima.tzinfo) - ultima).total_seconds() / 3600 if ultima else float("inf")
            if hace_h >= args.grilla_cada_horas:
                resultado_grilla = paso_grilla(db, pausa)
                if resultado_grilla == "parar":
                    break
                if resultado_grilla == "fallo" and not esperar(ESPERA_GRILLA_FALLIDA_S, "la grilla no se pudo completar"):
                    break
                ciclos += 1
                if args.max_ciclos and ciclos >= args.max_ciclos:
                    log.info("Se completaron %d ciclos", ciclos)
                    break
            elif resultado in ("vacia", "presupuesto"):
                # Sin trabajo para el detalle: se espera, pero sin pasarse de la hora de la próxima grilla.
                faltan_s = (args.grilla_cada_horas - hace_h) * 3600
                motivo = "esperando que se libere el presupuesto" if resultado == "presupuesto" else "no hay avisos por visitar"
                if not esperar(int(min(ESPERA_SIN_TRABAJO_S, max(faltan_s, 60))), motivo):
                    break
            # resultado == "listo": queda cola, sigue con la siguiente tanda
    finally:
        db.close()
    log.info("FIN orquestador | ciclos completos: %d", ciclos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
