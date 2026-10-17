"""Spike de detalle: baja unas pocas páginas de aviso y verifica dónde viven estado y precio.

Guarda el HTML en landing/_spike_detalle/ para inspeccionarlo sin volver a pedirlo.
Uso: python scripts/spike_detalle.py [N]
"""
import gzip
import json
import random
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import config  # noqa: E402
from common.db import conectar  # noqa: E402

RE_JSON_ESTADO = re.compile(r"_n\.ctx\.r=(\{.*?\});_n\.ctx\.r\.assets\.manifest=", re.DOTALL)


def buscar(nodo, pred, ruta="", salida=None, limite=12):
    """Recorre el JSON y junta (ruta, nodo) de los dicts que cumplen pred."""
    salida = [] if salida is None else salida
    if len(salida) >= limite:
        return salida
    if isinstance(nodo, dict):
        if pred(nodo):
            salida.append((ruta, nodo))
        for k, v in nodo.items():
            buscar(v, pred, f"{ruta}.{k}", salida, limite)
    elif isinstance(nodo, list):
        for i, v in enumerate(nodo):
            buscar(v, pred, f"{ruta}[{i}]", salida, limite)
    return salida


def main(n: int) -> None:
    con = conectar()
    with con.cursor() as cur:
        # Una URL por comuna distinta, para ver variedad.
        cur.execute("""SELECT DISTINCT ON (comuna) id_aviso, payload->>'url'
                       FROM bronze.grilla_avisos ORDER BY comuna, random()""")
        filas = cur.fetchall()
    con.close()
    random.shuffle(filas)

    destino = config.RUTA_LANDING / "_spike_detalle"
    destino.mkdir(parents=True, exist_ok=True)

    for id_aviso, url in filas[:n]:
        resp = requests.get(url, headers=config.HEADERS, timeout=20)
        html = resp.text
        (destino / f"{id_aviso}.html.gz").write_bytes(gzip.compress(html.encode("utf-8")))

        soup = BeautifulSoup(html, "lxml")
        canon = soup.find("link", attrs={"rel": "canonical"})
        og = soup.find("meta", attrs={"property": "og:url"})
        print(f"\n=== {id_aviso} status={resp.status_code} bytes={len(html)} url_final={resp.url[:90]}")
        print("  canonical contiene id:", id_aviso in (canon.get("href", "") if canon else ""),
              "| og:url contiene id:", id_aviso in (og.get("content", "") if og else ""))

        m = RE_JSON_ESTADO.search(html)
        if not m:
            print("  JSON _n.ctx.r NO encontrado")
        else:
            try:
                estado = json.loads(m.group(1))
                print("  JSON _n.ctx.r parseado OK, tamaño:", len(m.group(1)))
                for ruta, nodo in buscar(estado, lambda d: d.get("id") in (
                        "item_status_message", "item_status_short_description_message")):
                    print("  ESTADO en", ruta, "->", str(nodo.get("body"))[:150])
                for ruta, nodo in buscar(estado, lambda d: "original_value" in d or
                                         ("currency_id" in d and "value" in d), limite=4):
                    print("  PRECIO en", ruta, "->", {k: nodo[k] for k in nodo if k in
                          ("value", "currency_id", "original_value", "amount")})
            except json.JSONDecodeError as e:
                print("  JSON no parseable:", e)
        time.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
