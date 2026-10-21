"""Grilla: URLs permitidas por el robots.txt, tarjetas y cobertura. HTML sintético, sin red."""
import config
import scraper_grilla as g

TARJETA = """<ul><li class="ui-search-layout__item">
  <a class="poly-component__title" href="https://www.portalinmobiliario.com/MLC-123456789-depto#polycard_client=search&position=3">Depto en Ñuñoa</a>
  <div class="andes-money-amount poly-price__amount"><span class="andes-money-amount__currency-symbol">$</span>
  <span class="andes-money-amount__fraction">450.000</span></div>
  <span class="poly-component__location">Ñuñoa, Santiago</span>
  <span>2 dormitorios</span><span>1 baño</span><span>55 m² útiles</span>
</li></ul><p>1.234 resultados</p>"""


def test_url_de_primera_y_segunda_pagina():
    base = f"{config.BASE_URL}/{config.OPERACION}/departamento/nunoa-metropolitana"
    assert g.construir_url("departamento", "nunoa-metropolitana", 1) == base
    assert g.construir_url("departamento", "nunoa-metropolitana", 2).endswith(
        f"/_Desde_{1 + config.RESULTADOS_POR_PAGINA}_NoIndex_True")


def test_segmento_va_entre_el_tipo_y_la_comuna():
    u = g.construir_url("departamento", "nunoa-metropolitana", 1, "2-dormitorios")
    assert u.endswith("/departamento/2-dormitorios/nunoa-metropolitana")


def test_solo_filtros_permitidos_por_robots_txt():
    """El robots.txt bloquea _PriceRange_ y los filtros de superficie, baños y estacionamientos."""
    assert g.SEGMENTOS_DORMITORIOS == ["1-dormitorio", "2-dormitorios", "3-dormitorios"]
    urls = [g.construir_url("departamento", "las-condes-metropolitana", p, s)
            for p in (1, 2, 40) for s in (None, *g.SEGMENTOS_DORMITORIOS)]
    prohibido = ("_PriceRange_", "_TotalArea_", "_UsableArea_", "_Bathrooms_", "_ParkingSpaces_")
    assert not [u for u in urls if any(p in u for p in prohibido)]


def test_parsea_tarjeta_y_separa_el_fragmento_de_seguimiento():
    t = g.parsear_tarjetas(TARJETA)
    assert len(t) == 1
    t = t[0]
    assert t["id_aviso"] == "MLC-123456789" and t["precio"] == "450.000"
    assert t["dormitorios"] == "2" and t["banos"] == "1" and t["superficie_m2"] == "55"
    assert "#" not in t["url"] and t["url_fragmento"].startswith("polycard_client")


def test_tarjeta_sin_id_se_descarta():
    sin_id = '<li class="ui-search-layout__item"><a class="poly-component__title" href="/x">x</a></li>'
    assert g.parsear_tarjetas(sin_id) == []


def test_total_declarado():
    assert g.total_declarado(TARJETA) == 1234
    assert g.total_declarado("<p>sin total</p>") is None


def test_cobertura_completa_o_parcial():
    assert g.estado_cobertura(1000, 995, acotada=False) == "completa"   # tolera 1 % por avisos que entran y salen
    assert g.estado_cobertura(1000, 900, acotada=False) == "parcial"
    assert g.estado_cobertura(1000, 1000, acotada=True) == "parcial"    # --max-paginas nunca es completa
    assert g.estado_cobertura(None, 500, acotada=False) == "parcial"
