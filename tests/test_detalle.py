"""Extracción del detalle de un aviso con HTML sintético: sin red ni base de datos."""
import config
import scraper_detalle as d

HTML = """<html><body>
<div>Publicado hace 3 días</div>
<ul>
  <li>Superficie total 60 m²</li><li>Superficie útil 48,5 m²</li>
  <li>Dormitorios 2</li><li>Baños 1</li><li>Estacionamientos: 1</li><li>Bodegas 1</li>
  <li>Antigüedad 12 años</li><li>Amoblado: Sí</li><li>Admite mascotas: No</li>
  <li>Gastos comunes 85.000 CLP</li><li>Número de piso de la unidad 7</li>
</ul>
<div data-testid="core-description"><p>Departamento remodelado, luminoso.</p></div>
<script>{"latitude":"-33.45123","longitude":"-70.65432"}</script>
</body></html>"""


def test_extrae_campos_basicos():
    c = d.extraer_campos(HTML, None)
    assert c["dormitorios"] == "2" and c["banos"] == "1"
    assert c["superficie_util_m2"] == "48,5" and c["superficie_total_m2"] == "60"
    assert c["antiguedad_anos"] == "12" and c["piso_unidad"] == "7"
    assert c["amoblado"] == "Sí" and c["admite_mascotas"] == "No"
    assert c["gastos_comunes"] == "85.000"
    assert c["fecha_publicacion_texto"] == "hace 3 días"
    assert (c["latitud"], c["longitud"]) == ("-33.45123", "-70.65432")
    assert "remodelado" in c["descripcion"]


def test_campo_ausente_queda_en_none():
    c = d.extraer_campos("<html><body><p>nada</p></body></html>", None)
    assert c["dormitorios"] is None and c["antiguedad_anos"] is None and c["latitud"] is None


def test_json_de_la_pagina_valido_e_invalido():
    ok = 'x _n.ctx.r={"appProps":{"a":1}};_n.ctx.r.assets.manifest= y'
    assert d.extraer_json_pagina(ok) == {"appProps": {"a": 1}}
    assert d.extraer_json_pagina("sin estado") is None
    assert d.extraer_json_pagina("_n.ctx.r={roto};_n.ctx.r.assets.manifest=") is None


def test_precio_y_estado_del_json():
    comps = {"price": {"price": {"value": 450000, "currency_id": "CLP"}},
             "item_status_message": {"body": {"text": "Publicación finalizada"}}}
    assert d.extraer_precio(comps) == {"precio_valor": 450000, "precio_moneda": "CLP", "precio_original": None}
    assert d.extraer_estado_texto(comps) == "Publicación finalizada"
    assert d.extraer_estado_texto({}) is None
    assert d.extraer_precio({})["precio_valor"] is None


def test_hash_ignora_campos_volatiles():
    a = {"precio": "450.000", "fecha_publicacion_texto": "hace 3 días"}
    b = {"precio": "450.000", "fecha_publicacion_texto": "hace 4 días"}
    assert d.hash_observacion(a) == d.hash_observacion(b)
    assert d.hash_observacion(a) != d.hash_observacion({"precio": "460.000"})


def test_reglas_de_uso_responsable():
    """El User-Agent es de navegador (el identificado recibe una página sin precio, P-25) y el presupuesto diario tiene tope."""
    assert config.HEADERS["User-Agent"].startswith("Mozilla/5.0")
    assert d.PRESUPUESTO_24H <= 5000
