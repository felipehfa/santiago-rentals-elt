"""Estado del scraping en una pantalla: qué tanda corre (grilla o detalle), su avance y su desglose.

Solo lee la base y los logs locales; nunca hace requests al sitio ni toca el orquestador. Pensado para responder "¿cómo va?".

    Scraper DETALLE · tanda, avance, ritmo, motivos de la cola, resultados, estado visto y cambios
    Scraper GRILLA  · corrida, comuna y página en curso, cobertura por comuna, avisos nuevos y tarjetas cambiadas
    Scraper EN ESPERA · motivo y hora de retoma (y el resumen de la última tanda)
    Últimas 24 h: el mismo desglose del detalle para todas sus visitas, y el resumen de la grilla.
    Al final: presupuesto de 24 h, próxima grilla y radar de la zona de foco (si hay foco).

Uso:
    python scripts/como_va.py
"""
import ast
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import config  # noqa: E402
from common.db import conectar  # noqa: E402

LOG_DETALLE = RAIZ / "logs" / "detalle.log"
LOG_ORQUESTADOR = RAIZ / "logs" / "orquestador.log"
PRESUPUESTO_24H = 5000
NOMBRES_MOTIVO = {"nuevo": "nuevos", "rotacion": "rechequeo", "desaparecido": "desaparecidos",
                  "tarjeta_cambio": "tarjeta cambiada", "sin_precio": "sin precio"}

# Estado de publicación con la misma regla que Silver (010_construir_avisos.sql).
SQL_ESTADO = """CASE WHEN {c} IS NULL THEN 'activo' WHEN lower({c}) LIKE '%%finaliz%%' THEN 'finalizado'
                     WHEN lower({c}) LIKE '%%pausad%%' THEN 'pausado' ELSE 'otro' END"""

SQL_ZONA = """COALESCE(2 * 6371 * asin(sqrt(power(sin(radians({lat} - %(z_lat)s) / 2), 2)
              + cos(radians({lat})) * cos(radians(%(z_lat)s)) * power(sin(radians({lon} - %(z_lon)s) / 2), 2)))
              <= %(z_radio)s, false)"""


def miles(n) -> str:
    return f"{n:,.0f}".replace(",", ".") if n is not None else "-"


def hora(ts) -> str:
    return ts.astimezone().strftime("%H:%M") if ts else "-"


def consultar(cur, sql: str, params: dict | None = None) -> list[dict]:
    cur.execute(sql, params or {})
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, f)) for f in cur.fetchall()]


def cola_del_log() -> tuple[int | None, dict]:
    """Tamaño y motivos de la cola de la tanda en curso: la última línea 'Cola:' del log del detalle."""
    try:
        lineas = LOG_DETALLE.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        return None, {}
    for linea in reversed(lineas):
        m = re.search(r"Cola: (\d+) avisos (\{.*\})", linea)
        if m:
            try:
                return int(m.group(1)), ast.literal_eval(m.group(2))
            except (ValueError, SyntaxError):
                return int(m.group(1)), {}
    return None, {}


def espera_del_log() -> str | None:
    """Si el orquestador está esperando, su última línea 'Espera N min (motivo); retoma a las HH:MM'."""
    try:
        ultima = LOG_ORQUESTADOR.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1]
    except (OSError, IndexError):
        return None
    m = re.search(r"Espera \d+ min \((.*)\); retoma a las (\d\d:\d\d)", ultima)
    return f"{m.group(1)}; retoma a las {m.group(2)}" if m else None


def zona_params() -> dict:
    lat, lon, radio = config.ZONA_FOCO or (0, 0, -1)
    return {"z_lat": lat, "z_lon": lon, "z_radio": radio}


# ------------------------------------------------------------------ detalle

def resumen_detalle(cur, run: dict | None, en_curso: bool) -> list[str]:
    """Desglose de una tanda de detalle o, con run=None, de todas las visitas de las últimas 24 h."""
    rid = run["run_id"] if run else None
    p = {"rid": rid, **zona_params()}
    filtro_i = "run_id = %(rid)s" if run else "scraped_at > now() - interval '24 hours'"
    filtro_d = "d.run_id = %(rid)s" if run else "d.scraped_at > now() - interval '24 hours'"
    intentos = consultar(cur, f"""
        WITH i AS (SELECT * FROM bronze.detalle_intentos WHERE {filtro_i}),
        ult AS (SELECT DISTINCT ON (d.id_aviso) d.id_aviso, d.estado_texto,
                       (d.payload->>'latitud')::numeric AS lat, (d.payload->>'longitud')::numeric AS lon
                FROM bronze.detalle_avisos d JOIN (SELECT DISTINCT id_aviso FROM i) v USING (id_aviso)
                ORDER BY d.id_aviso, d.scraped_at DESC)
        SELECT i.motivo_visita, i.resultado,
               CASE WHEN i.resultado = 'ok' THEN {SQL_ESTADO.format(c='ult.estado_texto')} END AS estado,
               {SQL_ZONA.format(lat='ult.lat', lon='ult.lon')} AS en_zona
        FROM i LEFT JOIN ult USING (id_aviso)""", p)
    cambios = consultar(cur, f"""
        SELECT d.precio_valor IS DISTINCT FROM a.precio_valor AS precio,
               COALESCE(d.estado_texto, '') <> COALESCE(a.estado_texto, '') AS estado,
               a.id_aviso IS NULL AS primera
        FROM bronze.detalle_avisos d
        LEFT JOIN LATERAL (SELECT precio_valor, estado_texto, id_aviso FROM bronze.detalle_avisos a
                           WHERE a.id_aviso = d.id_aviso AND a.scraped_at < d.scraped_at
                           ORDER BY a.scraped_at DESC LIMIT 1) a ON true
        WHERE {filtro_d}""", p)

    hechas = len(intentos)
    total, motivos = cola_del_log() if en_curso else (None, {})
    minutos = max((datetime.now(run["inicio"].tzinfo) - run["inicio"]).total_seconds() / 60, 0.1) if en_curso else None
    if run is None:
        lineas = [f"Detalle últimas 24 h · {miles(hechas)} visitas"]
    elif en_curso:
        ritmo = hechas / minutos
        avance = f"{hechas}/{total} ({hechas / total:.0%})" if total else f"{hechas} visitas"
        resto = (total - hechas) / ritmo if total and ritmo > 0 else None
        fin = f" · termina ~{(datetime.now() + timedelta(minutes=resto)).strftime('%H:%M')}" if resto else ""
        lineas = [f"Scraper DETALLE · tanda {rid} · desde {hora(run['inicio'])} · {avance} · "
                  f"{ritmo:.1f} visitas/min{fin}".replace(f"{ritmo:.1f}", f"{ritmo:.1f}".replace(".", ","))]
    else:
        lineas = [f"  Última tanda de detalle {rid} · {hora(run['inicio'])}-{hora(run['fin'])} · {run['estado']} · "
                  f"{hechas} visitas"]

    if motivos:
        lineas.append("  Cola:        " + " · ".join(f"{NOMBRES_MOTIVO.get(k, k)} {v}" for k, v in motivos.items() if v))
    por_motivo: dict[str, int] = {}
    for f in intentos:
        por_motivo[f["motivo_visita"]] = por_motivo.get(f["motivo_visita"], 0) + 1
    zona = sum(1 for f in intentos if f["en_zona"])
    lineas.append("  Visitadas:   " + " · ".join(f"{NOMBRES_MOTIVO.get(k, k)} {v}" for k, v in por_motivo.items())
                  + (f" · zona metro {zona}" if config.ZONA_FOCO else ""))

    res: dict[str, int] = {}
    for f in intentos:
        res[f["resultado"]] = res.get(f["resultado"], 0) + 1
    orden = ("ok", "no_encontrado", "error", "proyecto", "bloqueado", "captcha")
    lineas.append("  Resultados:  " + " · ".join(f"{k.replace('_', ' ')} {res[k]}" for k in orden if res.get(k)))
    est: dict[str, int] = {}
    for f in intentos:
        if f["estado"]:
            est[f["estado"]] = est.get(f["estado"], 0) + 1
    lineas.append("    estado:    " + " · ".join(f"{k}s {est[k]}" if k != "otro" else f"otro {est[k]}"
                                                for k in ("activo", "pausado", "finalizado", "otro") if est.get(k)))
    n_precio = sum(1 for c in cambios if c["precio"] and not c["primera"])
    n_estado = sum(1 for c in cambios if c["estado"] and not c["primera"])
    n_primera = sum(1 for c in cambios if c["primera"])
    n_otros = sum(1 for c in cambios if not (c["precio"] or c["estado"] or c["primera"]))
    sin_cambio = res.get("ok", 0) - len(cambios)
    lineas.append(f"    cambios:   {n_precio} de precio · {n_estado} de estado · {n_otros} otros campos"
                  + (f" · {n_primera} primera observación" if n_primera else "") + f" · {sin_cambio} sin cambios")
    return lineas


# ------------------------------------------------------------------ grilla

def resumen_grilla(cur, run: dict, en_curso: bool) -> list[str]:
    rid = run["run_id"]
    paginas = consultar(cur, """SELECT comuna, count(*) AS n, max(scraped_at) AS ult FROM bronze.grilla_paginas
                                WHERE run_id = %(rid)s GROUP BY comuna ORDER BY min(scraped_at)""", {"rid": rid})
    cobertura = consultar(cur, """SELECT DISTINCT ON (comuna) comuna, total_declarado, avisos_unicos, estado
                                  FROM bronze.grilla_cobertura WHERE run_id = %(rid)s
                                  ORDER BY comuna, registrado_en DESC""", {"rid": rid})
    nuevos = consultar(cur, """SELECT count(*) AS n FROM bronze.grilla_vistos v
                               WHERE v.primera_vez >= %(ini)s AND v.ultimo_run_id = %(rid)s""",
                       {"rid": rid, "ini": run["inicio"]})[0]["n"]
    tarjetas = consultar(cur, """SELECT count(*) AS n FROM bronze.grilla_avisos g
                                 WHERE g.run_id = %(rid)s AND EXISTS (SELECT 1 FROM bronze.grilla_avisos a
                                     WHERE a.id_aviso = g.id_aviso AND a.run_id < %(rid)s)""", {"rid": rid})[0]["n"]
    hechas = {c["comuna"] for c in cobertura}
    comunas = config.COMUNAS_ACTIVAS
    if en_curso:
        actual = next((p for p in reversed(paginas) if p["comuna"] not in hechas), None)
        if actual:
            previas = consultar(cur, """SELECT count(*) AS n FROM bronze.grilla_paginas
                                        WHERE comuna = %(c)s AND run_id = (SELECT max(run_id) FROM bronze.grilla_cobertura
                                                                          WHERE comuna = %(c)s AND run_id < %(rid)s)""",
                                {"c": actual["comuna"], "rid": rid})[0]["n"]
            pos = comunas.index(actual["comuna"]) + 1 if actual["comuna"] in comunas else len(hechas) + 1
            en = (f"comuna {pos}/{len(comunas)} ({actual['comuna'].removesuffix('-metropolitana')}) · "
                  f"página {actual['n']}" + (f"/~{previas}" if previas else ""))
        else:
            en = f"{len(hechas)}/{len(comunas)} comunas listas"
        lineas = [f"Scraper GRILLA · corrida {rid} · desde {hora(run['inicio'])} · {en}"]
    else:
        lineas = [f"  Última grilla {rid} · {hora(run['inicio'])}-{hora(run['fin'])} · {run['estado']} · "
                  f"{run['paginas']} páginas"]
    for c in cobertura:
        pct = f"{c['avisos_unicos'] / c['total_declarado']:.0%}" if c["total_declarado"] else "-"
        pags = next((p["n"] for p in paginas if p["comuna"] == c["comuna"]), 0)
        lineas.append(f"  {c['comuna'].removesuffix('-metropolitana'):<12} {miles(c['avisos_unicos'])} de "
                      f"{miles(c['total_declarado'])} ({pct}, {c['estado']}) · {pags} páginas")
    lineas.append(f"  Encontrado:  {nuevos} avisos nuevos · {tarjetas} tarjetas cambiadas")
    return lineas


def resumen_grilla_24h(cur) -> list[str]:
    r = consultar(cur, """
        SELECT (SELECT count(*) FROM bronze.runs WHERE fuente = 'grilla' AND inicio > now() - interval '24 hours') AS corridas,
               (SELECT count(*) FROM bronze.grilla_paginas WHERE scraped_at > now() - interval '24 hours') AS paginas,
               (SELECT count(*) FROM bronze.grilla_vistos WHERE primera_vez > now() - interval '24 hours') AS nuevos,
               (SELECT count(*) FROM bronze.grilla_avisos g WHERE g.scraped_at > now() - interval '24 hours'
                  AND EXISTS (SELECT 1 FROM bronze.grilla_avisos a
                              WHERE a.id_aviso = g.id_aviso AND a.scraped_at < g.scraped_at)) AS tarjetas""")[0]
    return [f"Grilla últimas 24 h · {r['corridas']} corridas · {miles(r['paginas'])} páginas · "
            f"{r['nuevos']} avisos nuevos · {r['tarjetas']} tarjetas cambiadas"]


# ------------------------------------------------------------------ pie

def pie(cur) -> list[str]:
    usadas = consultar(cur, """SELECT count(*) AS n FROM bronze.detalle_intentos
                               WHERE scraped_at > now() - interval '24 hours' AND resultado <> 'bloqueado'""")[0]["n"]
    lineas = [f"Presupuesto 24 h: {miles(usadas)} de {miles(PRESUPUESTO_24H)} · quedan {miles(PRESUPUESTO_24H - usadas)}"]
    ult = consultar(cur, """SELECT max(inicio) AS ini FROM bronze.runs
                            WHERE fuente = 'grilla' AND estado IN ('success', 'parcial')""")[0]["ini"]
    if ult:
        prox = ult + timedelta(hours=config.GRILLA_CADA_HORAS)
        cuando = (f"próxima desde ~{hora(prox)}" if prox > datetime.now(prox.tzinfo)
                  else "atrasada: entra al terminar la tanda en curso")
        lineas.append(f"Grilla: última {ult.astimezone().strftime('%d-%m %H:%M')} · {cuando} "
                      f"(cada {config.GRILLA_CADA_HORAS:g} h)")
    if config.ZONA_FOCO:
        lat, lon, radio = config.ZONA_FOCO
        r = consultar(cur, f"""
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE p.costo_total_predicho_clp > 0
                                    AND a.costo_total_clp < p.costo_total_predicho_clp) AS bajo,
                   count(*) FILTER (WHERE p.costo_total_predicho_clp IS NULL AND a.apto_entrenamiento) AS pendientes,
                   count(*) FILTER (WHERE p.costo_total_predicho_clp IS NULL AND NOT a.apto_entrenamiento) AS no_aptos
            FROM gold.aviso_entrenamiento a
            -- Misma regla que gold.predicciones_vigentes, pero solo para los avisos filtrados: la vista ordena
            -- todo el historial (~940 mil filas, ~45 s) y aquí bastan unas decenas de búsquedas por índice.
            LEFT JOIN LATERAL (SELECT costo_total_predicho_clp FROM gold.predicciones p WHERE p.id_aviso = a.id_aviso
                               ORDER BY modelo_version DESC, predicho_en DESC LIMIT 1) p ON true
            WHERE a.estado_publicacion = 'activo' AND a.primera_vez_visto >= now() - interval '24 hours'
              AND {SQL_ZONA.format(lat='a.latitud', lon='a.longitud')}""", zona_params())[0]
        # Sin predicción puede ser "aún no" (apto, espera al próximo scoring) o "nunca" (no apto para el modelo).
        sin = [t for t in (f"{r['pendientes']} esperan el scoring" if r["pendientes"] else "",
                           f"{r['no_aptos']} no aptos" if r["no_aptos"] else "") if t]
        lineas.append(f"Radar: {r['n']} avisos nuevos en la zona en 24 h, {r['bajo']} bajo la predicción"
                      + (f" ({', '.join(sin)})" if sin else "") + " · python scripts/radar.py --horas 24")
    return lineas


def main() -> int:
    try:
        con = conectar("BD_STRING")
    except Exception as e:  # el mensaje de la librería puede traer parte de la cadena de conexión
        print(f"No se pudo conectar ({type(e).__name__})")
        return 1
    try:
        with con.cursor() as cur:
            ultimo = consultar(cur, "SELECT * FROM bronze.runs ORDER BY run_id DESC LIMIT 1")[0]
            # Una corrida cortada a la fuerza queda 'en_curso' para siempre, pero solo la más nueva puede estar corriendo.
            en_curso = ultimo["estado"] == "en_curso"
            salida: list[str] = []
            if en_curso:
                fn = resumen_grilla if ultimo["fuente"] == "grilla" else resumen_detalle
                salida += fn(cur, ultimo, True)
            else:
                salida.append(f"Scraper EN ESPERA · {espera_del_log() or 'sin tanda en curso'}")
                for fuente, fn in (("detalle", resumen_detalle), ("grilla", resumen_grilla)):
                    r = consultar(cur, "SELECT * FROM bronze.runs WHERE fuente = %(f)s ORDER BY run_id DESC LIMIT 1",
                                  {"f": fuente})
                    if r:
                        salida += fn(cur, r[0], False)
            salida.append("")
            salida += resumen_detalle(cur, None, False)
            salida += resumen_grilla_24h(cur)
            salida.append("")
            salida += pie(cur)
        con.rollback()
    finally:
        con.close()
    print("\n".join(salida))
    return 0


if __name__ == "__main__":
    sys.exit(main())
