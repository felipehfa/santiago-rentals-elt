"""Radar de arriendo: avisos activos cerca de config.ZONA_FOCO, del más barato al más caro respecto de la predicción.

Herramienta temporal para la búsqueda personal de arriendo (foco del 2026-11-18). Solo lee Gold (no hace requests al sitio).
Compara el costo total publicado (arriendo + gastos comunes) con el que predice el modelo @champion: un % negativo es un
aviso más barato de lo que el modelo espera para sus características y ubicación.

Uso:
    python scripts/radar.py                     # todos los activos de la zona
    python scripts/radar.py --horas 24          # solo los vistos por primera vez en las últimas 24 h
    python scripts/radar.py --radio 1 --dorm 2 --max-costo 650000
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import config  # noqa: E402
from common.db import conectar  # noqa: E402

SQL = """
WITH base AS (
  SELECT a.id_aviso, a.comuna, a.dormitorios, a.banos, a.superficie_util_m2, a.costo_total_clp, a.primera_vez_visto,
         a.fecha_publicacion_aprox, a.url, a.apto_entrenamiento, p.costo_total_predicho_clp, p.etiqueta,
         1000 * 2 * 6371 * asin(sqrt(power(sin(radians(a.latitud - %(lat)s) / 2), 2)
             + cos(radians(a.latitud)) * cos(radians(%(lat)s)) * power(sin(radians(a.longitud - %(lon)s) / 2), 2))) AS dist_m
  FROM gold.aviso_entrenamiento a
  -- Misma regla que gold.predicciones_vigentes, pero solo para los avisos filtrados (la vista ordena todo el historial).
  LEFT JOIN LATERAL (SELECT costo_total_predicho_clp, etiqueta FROM gold.predicciones p WHERE p.id_aviso = a.id_aviso
                     ORDER BY modelo_version DESC, predicho_en DESC LIMIT 1) p ON true
  WHERE a.estado_publicacion = 'activo' AND a.latitud IS NOT NULL
    AND a.primera_vez_visto >= now() - make_interval(hours => %(horas)s)
)
SELECT * FROM base
WHERE dist_m <= %(radio_m)s
  AND (%(dorm)s IS NULL OR dormitorios = %(dorm)s)
  AND (%(max_costo)s IS NULL OR costo_total_clp <= %(max_costo)s)
ORDER BY costo_total_clp / NULLIF(costo_total_predicho_clp, 0) NULLS LAST, dist_m
"""


def main() -> int:
    if config.ZONA_FOCO is None:
        print("No hay zona de foco en config.ZONA_FOCO.")
        return 1
    lat, lon, radio_km = config.ZONA_FOCO
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--radio", type=float, default=radio_km, help="km desde el punto de foco")
    ap.add_argument("--horas", type=int, default=24 * 365 * 10, help="solo avisos vistos por primera vez en estas horas")
    ap.add_argument("--dorm", type=int, default=None, help="dormitorios exactos")
    ap.add_argument("--max-costo", type=float, default=None, help="costo total máximo (CLP, con gastos comunes)")
    ap.add_argument("--limite", type=int, default=40)
    args = ap.parse_args()

    try:
        con = conectar("BD_STRING")
    except Exception as e:  # el mensaje de la librería puede traer parte de la cadena de conexión
        print(f"No se pudo conectar ({type(e).__name__})")
        return 1
    try:
        with con.cursor() as cur:
            cur.execute(SQL, {"lat": lat, "lon": lon, "radio_m": args.radio * 1000, "horas": args.horas,
                              "dorm": args.dorm, "max_costo": args.max_costo})
            cols = [c[0] for c in cur.description]
            filas = [dict(zip(cols, f)) for f in cur.fetchall()]
    finally:
        con.close()

    esperan = sum(1 for f in filas if f["costo_total_predicho_clp"] is None and f["apto_entrenamiento"])
    print(f"{len(filas)} avisos activos a {args.radio:g} km o menos del foco"
          + (f", nuevos en {args.horas} h" if args.horas < 24 * 365 else "")
          + (f" ({esperan} esperan el scoring: dif = esp)" if esperan else ""))
    print(f"{'comuna':<12}{'dorm':>5}{'baños':>6}{'m2':>6}{'costo':>10}{'modelo':>10}{'dif':>6}  {'dist':>6}  url")
    for f in filas[:args.limite]:
        costo, pred = f["costo_total_clp"], f["costo_total_predicho_clp"]
        # Sin predicción: "esp" = apto, espera el próximo scoring; "n/a" = no apto, el modelo no lo evalúa.
        dif = (f"{(costo / pred - 1) * 100:+.0f}%" if costo and pred
               else "esp" if f["apto_entrenamiento"] else "n/a")
        def n(x, ancho):
            return f"{x:>{ancho},.0f}".replace(",", ".") if x is not None else f"{'-':>{ancho}}"
        print(f"{f['comuna'].removesuffix('-metropolitana'):<12}{n(f['dormitorios'], 5)}{n(f['banos'], 6)}"
              f"{n(f['superficie_util_m2'], 6)}{n(costo, 10)}{n(pred, 10)}{dif:>6}  {f['dist_m']:>5.0f}m  {f['url'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
