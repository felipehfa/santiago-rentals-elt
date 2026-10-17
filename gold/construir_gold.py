"""Construye la capa Gold desde Silver: los dos SCD2 (estado y precio) y el dataset de entrenamiento.

Gold solo lee de Silver. Se reconstruye completa en una transacción con una instantánea fija de los datos;
si algo falla, las tablas anteriores quedan intactas.

Uso:
    python gold/construir_gold.py
"""
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from common.db import conectar  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("gold")

RUTA_SQL = Path(__file__).resolve().parent / "sql"


def aplicar_ddl(con) -> None:
    with con, con.cursor() as cur:
        cur.execute((RUTA_SQL / "001_schema.sql").read_text(encoding="utf-8"))
    log.info("DDL de gold aplicado")


def verificar(cur) -> None:
    """Chequeos de integridad de los SCD2. Si alguno falla se aborta y no se guarda nada."""
    # Cada aviso con observaciones debe tener exactamente un intervalo vigente en cada SCD2.
    for tabla in ("dim_estado_aviso_scd2", "dim_precio_aviso_scd2"):
        cur.execute(f"""SELECT count(*) FROM (
                            SELECT id_aviso FROM gold.{tabla} GROUP BY id_aviso
                            HAVING count(*) FILTER (WHERE is_current) <> 1) t""")
        malos = cur.fetchone()[0]
        if malos:
            raise RuntimeError(f"{malos} avisos sin exactamente un intervalo vigente en gold.{tabla}")
        # Los intervalos de un aviso no pueden solaparse ni tener huecos: valid_to de uno = valid_from del siguiente.
        cur.execute(f"""SELECT count(*) FROM (
                            SELECT valid_to, LEAD(valid_from) OVER (PARTITION BY id_aviso ORDER BY valid_from) AS sig
                            FROM gold.{tabla}) t
                        WHERE valid_to IS NOT NULL AND valid_to <> sig""")
        malos = cur.fetchone()[0]
        if malos:
            raise RuntimeError(f"{malos} intervalos de gold.{tabla} con hueco o solape")
    cur.execute("SELECT count(*) FROM gold.aviso_entrenamiento WHERE apto_entrenamiento AND costo_total_clp IS NULL")
    malos = cur.fetchone()[0]
    if malos:
        raise RuntimeError(f"{malos} avisos aptos sin costo total")


def construir(con) -> None:
    with con.cursor() as cur:
        cur.execute("INSERT INTO gold.construcciones DEFAULT VALUES RETURNING id")
        id_construccion = cur.fetchone()[0]
    con.commit()

    try:
        with con.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            for archivo in ("010_scd2.sql", "020_aviso_entrenamiento.sql"):
                cur.execute((RUTA_SQL / archivo).read_text(encoding="utf-8"))
            verificar(cur)
        con.commit()
    except Exception as e:
        con.rollback()
        with con, con.cursor() as cur:
            cur.execute("UPDATE gold.construcciones SET fin = now(), detalle = %s WHERE id = %s",
                        (f"error: {e}", id_construccion))
        raise
    with con, con.cursor() as cur:
        cur.execute("UPDATE gold.construcciones SET fin = now() WHERE id = %s", (id_construccion,))


def resumen(con) -> None:
    with con.cursor() as cur:
        for tabla in ("dim_estado_aviso_scd2", "dim_precio_aviso_scd2"):
            cur.execute(f"SELECT count(*), count(DISTINCT id_aviso), count(*) FILTER (WHERE is_current) "
                        f"FROM gold.{tabla}")
            log.info("%-24s intervalos=%d avisos=%d vigentes=%d", tabla, *cur.fetchone())
        cur.execute("SELECT count(*), count(*) FILTER (WHERE apto_entrenamiento) FROM gold.aviso_entrenamiento")
        total, aptos = cur.fetchone()
        log.info("aviso_entrenamiento: %d avisos, %d aptos", total, aptos)
        cur.execute("""SELECT m, count(*) FROM gold.aviso_entrenamiento,
                       LATERAL unnest(string_to_array(motivo_exclusion, ',')) AS m
                       GROUP BY 1 ORDER BY 2 DESC""")
        log.info("motivos de exclusión (un aviso puede tener varios): %s", cur.fetchall())
        cur.execute("""SELECT estado_publicacion, count(*) FROM gold.aviso_entrenamiento
                       WHERE apto_entrenamiento GROUP BY 1 ORDER BY 2 DESC""")
        log.info("aptos por estado: %s", cur.fetchall())


def main() -> int:
    con = conectar()
    try:
        aplicar_ddl(con)
        construir(con)
        resumen(con)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
