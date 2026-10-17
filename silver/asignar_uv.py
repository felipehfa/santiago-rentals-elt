"""Cruce punto-en-polígono: ubica cada aviso con coordenadas dentro de su Unidad Vecinal (IGVUST).

Lee los polígonos de bronze.igvust_uv y las coordenadas de silver.avisos, y llena silver.aviso_uv. Se llama
desde construir_silver.py con el cursor de la transacción de construcción, para que todo Silver quede con la
misma instantánea de Bronce. Usa shapely (STRtree) y no PostGIS, para no depender de una extensión de la base.
"""
import logging

import numpy as np
import shapely
from psycopg2.extras import execute_values

log = logging.getLogger("silver")


def asignar_uv(cur) -> tuple[int, int]:
    """Devuelve (avisos con coordenadas, avisos que cayeron dentro de alguna UV)."""
    cur.execute("SELECT uv_rsh, geometria_wkt FROM bronze.igvust_uv")
    filas = cur.fetchall()
    if not filas:
        raise RuntimeError("bronze.igvust_uv está vacía: correr bronze/cargar_igvust.py antes de construir Silver")
    ids_uv = np.array([f[0] for f in filas], dtype=np.int64)
    poligonos = shapely.from_wkt([f[1] for f in filas])
    arbol = shapely.STRtree(poligonos)

    cur.execute("SELECT id_aviso, longitud, latitud FROM silver.avisos WHERE latitud IS NOT NULL AND longitud IS NOT NULL")
    avisos = cur.fetchall()
    cur.execute("TRUNCATE silver.aviso_uv")
    if not avisos:
        return 0, 0

    ids_aviso = [a[0] for a in avisos]
    puntos = shapely.points([float(a[1]) for a in avisos], [float(a[2]) for a in avisos])
    idx_punto, idx_poligono = arbol.query(puntos, predicate="within")

    # Un punto sobre el borde entre dos UV puede caer en ambas: se queda con la de menor id, de forma
    # determinista, para que reconstruir Silver dé siempre el mismo resultado.
    elegido: dict[int, int] = {}
    for p, g in zip(idx_punto, idx_poligono):
        uv = int(ids_uv[g])
        if p not in elegido or uv < elegido[p]:
            elegido[p] = uv

    execute_values(cur, "INSERT INTO silver.aviso_uv (id_aviso, uv_rsh) VALUES %s",
                   [(ids_aviso[p], uv) for p, uv in elegido.items()])
    log.info("Unidad Vecinal: %d de %d avisos con coordenadas cayeron dentro de una UV", len(elegido), len(avisos))
    return len(avisos), len(elegido)
