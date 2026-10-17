"""Carga el shapefile IGVUST (nivel socioeconómico por Unidad Vecinal) a bronze.igvust_uv.

Es una carga de referencia estática: reemplaza la tabla completa dentro de una transacción. Solo se
carga la región pedida (por defecto la Metropolitana, cod_reg = 13) para no guardar polígonos que no se usan.

Uso:
    python bronze/cargar_igvust.py
    python bronze/cargar_igvust.py --region 13 --archivo datos_externos/igvust/202505_IGVUST_UV_cuartil.shp
"""
import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import shapely
from psycopg2.extras import execute_values

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from common.db import conectar  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("igvust")

ARCHIVO_DEFECTO = RAIZ / "datos_externos" / "igvust" / "202505_IGVUST_UV_cuartil.shp"
CRS_DESTINO = 4326  # lat/lon, igual que las coordenadas de los avisos
PRECISION_WKT = 6   # ~0,1 m: suficiente para ubicar un aviso, y 3 veces más liviano que el texto completo


def leer_region(archivo: Path, cod_reg: int) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(archivo, where=f"cod_reg = {cod_reg}")
    if gdf.empty:
        raise RuntimeError(f"El archivo no tiene Unidades Vecinales de la región {cod_reg}")
    if gdf.crs is None:
        raise RuntimeError("El shapefile no declara su sistema de coordenadas")
    gdf = gdf.to_crs(CRS_DESTINO)
    if not gdf.geometry.is_valid.all():
        # Un polígono inválido rompe el cruce punto-en-polígono sin avisar; se repara antes de guardar.
        gdf["geometry"] = gdf.geometry.make_valid()
        log.warning("Se repararon polígonos inválidos")
    return gdf


def cargar(archivo: Path, cod_reg: int) -> int:
    gdf = leer_region(archivo, cod_reg)
    filas = [
        (int(r.uv_rsh), int(r.cod_com), r.Comuna, int(r.cod_reg), r.Region,
         int(r.rank_nac), int(r.c_ig_com), int(r.c_ig_reg), int(r.c_ig_nac),
         float(r.pob_rsh_uv), float(r.hog_uv), float(r.p_urbano),
         shapely.to_wkt(r.geometry, rounding_precision=PRECISION_WKT), archivo.name)
        for r in gdf.itertuples(index=False)
    ]
    con = conectar()
    try:
        with con, con.cursor() as cur:
            cur.execute("TRUNCATE bronze.igvust_uv")
            execute_values(
                cur,
                """INSERT INTO bronze.igvust_uv
                   (uv_rsh, cod_com, comuna, cod_reg, region, rank_nac, c_ig_com, c_ig_reg, c_ig_nac,
                    pob_rsh_uv, hog_uv, p_urbano, geometria_wkt, archivo_origen) VALUES %s""",
                filas,
            )
    finally:
        con.close()
    log.info("Cargadas %d Unidades Vecinales de %d comunas (región %d)", len(filas), gdf.Comuna.nunique(), cod_reg)
    return len(filas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archivo", type=Path, default=ARCHIVO_DEFECTO)
    ap.add_argument("--region", type=int, default=13, help="código de región (13 = Metropolitana)")
    args = ap.parse_args()
    cargar(args.archivo, args.region)
    return 0


if __name__ == "__main__":
    sys.exit(main())
