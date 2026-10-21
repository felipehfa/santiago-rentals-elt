"""Cuándo toca reconstruir Silver y Gold: depende solo del archivo de estado."""
from datetime import datetime, timedelta

import orquestador as o
import scraper_detalle


def _estado(monkeypatch, **claves):
    monkeypatch.setattr(o, "leer_estado_silver_gold", lambda: claves)


def _hace(minutos: float) -> str:
    return (datetime.now() - timedelta(minutes=minutos)).isoformat(timespec="seconds")


def test_sin_estado_toca(monkeypatch):
    _estado(monkeypatch)
    assert o.toca_silver_gold(1.0)


def test_toca_pasada_la_hora(monkeypatch):
    _estado(monkeypatch, ok=_hace(61))
    assert o.toca_silver_gold(1.0)


def test_no_toca_antes_de_la_hora(monkeypatch):
    _estado(monkeypatch, ok=_hace(30))
    assert not o.toca_silver_gold(1.0)


def test_tras_un_fallo_espera_30_minutos(monkeypatch):
    _estado(monkeypatch, ok=_hace(120), fallo=_hace(10))
    assert not o.toca_silver_gold(1.0)
    _estado(monkeypatch, ok=_hace(120), fallo=_hace(31))
    assert o.toca_silver_gold(1.0)


def test_estado_ilegible_toca(monkeypatch):
    _estado(monkeypatch, ok="no es una fecha")
    assert o.toca_silver_gold(1.0)


def test_presupuesto_por_defecto_es_el_acordado():
    assert scraper_detalle.PRESUPUESTO_24H == 5000
