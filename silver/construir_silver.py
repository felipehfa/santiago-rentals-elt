"""Construye la capa Silver desde Bronce: aplica el DDL, carga los indicadores (UF y dólar) y reconstruye
silver.avisos dentro de una transacción.

Silver es derivada y reconstruible: se puede ejecutar las veces que se quiera, y si algo falla la tabla
anterior queda intacta.

Uso:
    python silver/construir_silver.py
"""
import logging
import sys
from datetime import date
from pathlib import Path

import requests
from psycopg2.extras import execute_values

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from common.db import conectar  # noqa: E402
from silver.asignar_uv import asignar_uv  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("silver")

API_INDICADOR = "https://mindicador.cl/api/{indicador}/{anio}"
INDICADORES = ("uf", "dolar")
RUTA_SQL = Path(__file__).resolve().parent / "sql"


def aplicar_ddl(con) -> None:
    with con, con.cursor() as cur:
        cur.execute((RUTA_SQL / "001_schema.sql").read_text(encoding="utf-8"))
    log.info("DDL de silver aplicado")


def cargar_indicadores(con) -> None:
    """Trae UF y dólar de los años que cubren las observaciones de Bronce. Una llamada por indicador y año;
    la UF trae el año completo, incluidos días futuros ya publicados."""
    with con.cursor() as cur:
        cur.execute("SELECT min(scraped_at)::date FROM bronze.grilla_avisos")
        primer_dia = cur.fetchone()[0] or date.today()

    for indicador in INDICADORES:
        for anio in range(primer_dia.year, date.today().year + 1):
            resp = requests.get(API_INDICADOR.format(indicador=indicador, anio=anio), timeout=30)
            resp.raise_for_status()
            filas = [(indicador, p["fecha"][:10], p["valor"]) for p in resp.json().get("serie", [])]
            if not filas:
                raise RuntimeError(f"mindicador.cl no devolvió datos de {indicador} para {anio}")
            with con, con.cursor() as cur:
                execute_values(
                    cur,
                    """INSERT INTO silver.indicadores_diarios (indicador, fecha, valor) VALUES %s
                       ON CONFLICT (indicador, fecha) DO UPDATE SET valor = EXCLUDED.valor, cargado_en = now()""",
                    filas,
                )
            log.info("%s %d: %d valores (hasta %s)", indicador, anio, len(filas), max(f[1] for f in filas))


def construir_avisos(con) -> int:
    """Reconstruye silver.avisos. Si queda algún precio en UF o USD sin su indicador, falla y no guarda nada:
    mejor detener la corrida que dejar precios en CLP calculados con un valor equivocado o inexistente."""
    with con.cursor() as cur:
        cur.execute("INSERT INTO silver.construcciones DEFAULT VALUES RETURNING id")
        id_construccion = cur.fetchone()[0]
    con.commit()

    try:
        # Las dos tablas se reconstruyen en la misma transacción: nunca queda una nueva y la otra vieja.
        with con.cursor() as cur:
            # Una sola instantánea de Bronce para ambas tablas: los scrapers siguen insertando mientras se
            # construye Silver, y con el aislamiento por defecto cada sentencia vería datos distintos.
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute((RUTA_SQL / "010_construir_avisos.sql").read_text(encoding="utf-8"))
            asignar_uv(cur)  # necesita las coordenadas que acaba de dejar 010
            cur.execute((RUTA_SQL / "030_unidad_vecinal.sql").read_text(encoding="utf-8"))
            cur.execute((RUTA_SQL / "020_construir_observaciones.sql").read_text(encoding="utf-8"))
            cur.execute("SELECT count(*) FROM silver.avisos")
            filas = cur.fetchone()[0]
            for tabla in ("avisos", "aviso_observaciones"):
                cur.execute(f"SELECT count(*) FROM silver.{tabla} WHERE moneda_sin_valor")
                sin_valor = cur.fetchone()[0]
                if sin_valor:
                    raise RuntimeError(
                        f"{sin_valor} filas de silver.{tabla} con precio en UF o USD y sin indicador para su fecha")
        con.commit()
    except Exception as e:
        con.rollback()
        with con, con.cursor() as cur:
            cur.execute("UPDATE silver.construcciones SET fin = now(), detalle = %s WHERE id = %s",
                        (f"error: {e}", id_construccion))
        raise

    with con, con.cursor() as cur:
        cur.execute("UPDATE silver.construcciones SET fin = now(), filas_avisos = %s WHERE id = %s",
                    (filas, id_construccion))
    return filas


def resumen(con) -> None:
    consultas = {
        "avisos": "SELECT count(*) FROM silver.avisos",
        "con detalle": "SELECT count(*) FROM silver.avisos WHERE tiene_detalle",
        "proyectos": "SELECT count(*) FROM silver.avisos WHERE es_proyecto",
        "fuera de grilla": "SELECT count(*) FROM silver.avisos WHERE fuera_de_grilla",
        "con unidad vecinal": "SELECT count(*) FROM silver.avisos WHERE uv_rsh IS NOT NULL",
        "sin polígono": "SELECT count(*) FROM silver.avisos WHERE uv_sin_poligono",
        "observaciones": "SELECT count(*) FROM silver.aviso_observaciones",
        "avisos con >1 obs.": "SELECT count(*) FROM (SELECT id_aviso FROM silver.aviso_observaciones "
                              "GROUP BY 1 HAVING count(*) > 1) t",
    }
    with con.cursor() as cur:
        for nombre, sql in consultas.items():
            cur.execute(sql)
            log.info("%-18s %d", nombre, cur.fetchone()[0])
        cur.execute("SELECT estado_publicacion, count(*) FROM silver.avisos GROUP BY 1 ORDER BY 2 DESC")
        log.info("estados: %s", cur.fetchall())
        cur.execute("""SELECT count(*) FILTER (WHERE coordenada_fuera_de_region), count(*) FILTER (WHERE conteo_imposible),
                              count(*) FILTER (WHERE superficie_util_sospechosa), count(*) FILTER (WHERE precio_sospechoso),
                              count(*) FILTER (WHERE gastos_comunes_faltante), count(*) FILTER (WHERE sin_coordenadas),
                              count(*) FILTER (WHERE precio_m2_atipico)
                       FROM silver.avisos""")
        log.info("banderas (coord. fuera de región, conteo imposible, superficie sospechosa, precio sospechoso, "
                 "gastos faltantes, sin coordenadas, precio por m2 atípico): %s", cur.fetchone())


def main() -> int:
    con = conectar()
    try:
        aplicar_ddl(con)
        cargar_indicadores(con)
        filas = construir_avisos(con)
        log.info("silver.avisos reconstruida: %d filas", filas)
        resumen(con)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
