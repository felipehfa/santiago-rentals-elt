"""Cruce punto-en-polígono: ubica cada aviso con coordenadas dentro de su Unidad Vecinal (IGVUST).

Lee los polígonos de bronze.igvust_uv y las coordenadas de silver.avisos, y llena silver.aviso_uv. Se llama
desde construir_silver.py con el cursor de la transacción de construcción, para que todo Silver quede con la
misma instantánea de Bronce. Usa shapely (STRtree) y no PostGIS, para no depender de una extensión de la base.

Es incremental. silver.aviso_uv funciona como caché: guarda las coordenadas con que se asignó cada aviso y una "base" (la
carga del IGVUST más las comunas usadas). Solo se cruzan los avisos nuevos o con coordenadas distintas; si cambia la base
(se volvió a cargar el archivo, o cambió la lista de comunas) se descarta el caché y se recalcula todo. Solo se usan los
polígonos de las comunas pedidas: la tabla de Bronce trae toda la Región Metropolitana.
"""
import logging

import numpy as np
import shapely
from psycopg2.extras import execute_values

log = logging.getLogger("silver")


def asignar_uv(cur, cods_comuna: list[int]) -> tuple[int, int]:
    """Devuelve (avisos con coordenadas, avisos que cayeron dentro de alguna UV)."""
    cur.execute("SELECT max(cargado_en) FROM bronze.igvust_uv")
    carga = cur.fetchone()[0]
    if carga is None:
        raise RuntimeError("bronze.igvust_uv está vacía: correr bronze/cargar_igvust.py antes de construir Silver")
    base = f"{carga.isoformat()}|{','.join(str(c) for c in sorted(cods_comuna))}"

    # Un caché de otra base (u otra versión de la tabla, sin base) no sirve: se descarta entero.
    cur.execute("DELETE FROM silver.aviso_uv WHERE base IS DISTINCT FROM %s", (base,))
    # Fuera los que ya no tienen coordenadas o ya no existen en silver.avisos.
    cur.execute("""DELETE FROM silver.aviso_uv u WHERE NOT EXISTS (
                       SELECT 1 FROM silver.avisos a
                       WHERE a.id_aviso = u.id_aviso AND a.latitud IS NOT NULL AND a.longitud IS NOT NULL)""")
    # Pendientes: avisos con coordenadas que no están en el caché o cuyas coordenadas cambiaron.
    cur.execute("""SELECT a.id_aviso, a.longitud, a.latitud
                   FROM silver.avisos a LEFT JOIN silver.aviso_uv u ON u.id_aviso = a.id_aviso
                   WHERE a.latitud IS NOT NULL AND a.longitud IS NOT NULL
                     AND (u.id_aviso IS NULL OR u.latitud IS DISTINCT FROM a.latitud OR u.longitud IS DISTINCT FROM a.longitud)""")
    pendientes = cur.fetchall()

    if pendientes:
        cur.execute("SELECT uv_rsh, geometria_wkt FROM bronze.igvust_uv WHERE cod_com = ANY(%s)", (list(cods_comuna),))
        filas = cur.fetchall()
        if not filas:
            raise RuntimeError("bronze.igvust_uv no tiene polígonos de las comunas pedidas")
        ids_uv = np.array([f[0] for f in filas], dtype=np.int64)
        arbol = shapely.STRtree(shapely.from_wkt([f[1] for f in filas]))

        puntos = shapely.points([float(a[1]) for a in pendientes], [float(a[2]) for a in pendientes])
        idx_punto, idx_poligono = arbol.query(puntos, predicate="within")

        # Un punto sobre el borde entre dos UV puede caer en ambas: se queda con la de menor id, de forma
        # determinista, para que reconstruir Silver dé siempre el mismo resultado.
        elegido: dict[int, int] = {}
        for p, g in zip(idx_punto, idx_poligono, strict=True):
            uv = int(ids_uv[g])
            if p not in elegido or uv < elegido[p]:
                elegido[p] = uv

        cur.execute("DELETE FROM silver.aviso_uv WHERE id_aviso = ANY(%s)", ([a[0] for a in pendientes],))
        execute_values(
            cur, "INSERT INTO silver.aviso_uv (id_aviso, uv_rsh, latitud, longitud, base) VALUES %s",
            [(a[0], elegido.get(i), a[2], a[1], base) for i, a in enumerate(pendientes)])

    cur.execute("SELECT count(*), count(uv_rsh) FROM silver.aviso_uv")
    total, con_uv = cur.fetchone()
    log.info("Unidad Vecinal: %d de %d avisos con coordenadas cayeron dentro de una UV (%d cruzados ahora)",
             con_uv, total, len(pendientes))
    return total, con_uv
