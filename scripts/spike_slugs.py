"""Spike: verifica que cada slug de comuna exista y mide cuántos avisos devuelve la página 1.

Guarda el HTML de cada comuna en landing/_spike/ para inspeccionar la estructura sin volver a pedir.
Uso: python scripts/spike_slugs.py
"""
import gzip
import random
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

SELECTORES_TARJETA = ["div.ui-search-result__wrapper", "div.andes-card", "li.ui-search-layout__item"]
RE_TOTAL = re.compile(r"([\d.]+)\s+resultados", re.IGNORECASE)


def main() -> None:
    destino = config.RUTA_LANDING / "_spike"
    destino.mkdir(parents=True, exist_ok=True)

    for comuna in config.COMUNAS_RM:
        url = f"{config.BASE_URL}/{config.OPERACION}/departamento/{comuna}"
        try:
            resp = requests.get(url, headers=config.HEADERS, timeout=20)
        except requests.RequestException as e:
            print(f"{comuna:40s} ERROR RED {e}")
            continue

        html = resp.text
        (destino / f"{comuna}.html.gz").write_bytes(gzip.compress(html.encode("utf-8")))

        soup = BeautifulSoup(html, "lxml")
        n_tarjetas = 0
        for sel in SELECTORES_TARJETA:
            encontradas = soup.select(sel)
            if encontradas:
                n_tarjetas = len(encontradas)
                break
        m = RE_TOTAL.search(soup.get_text(" ", strip=True))
        total = m.group(1) if m else "?"
        print(f"{comuna:40s} status={resp.status_code} bytes={len(html):>8} "
              f"tarjetas={n_tarjetas:>3} total_declarado={total} url_final={resp.url}")

        time.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))


if __name__ == "__main__":
    main()
