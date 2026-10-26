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


def test_baja_esperada_solo_para_desaparecido_en_su_misma_url():
    url = "https://www.portalinmobiliario.com/MLC-123-depto-_JM"
    baja = {"resultado": "no_encontrado", "http_status": 200, "url_final": url}
    assert d.es_baja_esperada({"id_aviso": "MLC-123", "motivo": "desaparecido"}, baja)
    # en otro motivo, o si redirige a otra página (posible muro), o si es error de red, sí cuenta como fallo
    assert not d.es_baja_esperada({"id_aviso": "MLC-123", "motivo": "rotacion"}, baja)
    assert not d.es_baja_esperada({"id_aviso": "MLC-123", "motivo": "desaparecido"},
                                  {**baja, "url_final": "https://www.portalinmobiliario.com/otra-cosa"})
    assert not d.es_baja_esperada({"id_aviso": "MLC-123", "motivo": "desaparecido"},
                                  {"resultado": "error", "http_status": None, "url_final": None})


def test_hash_ignora_fecha_de_plantilla_en_descripcion():
    a = {"descripcion": "Linda propiedad. Sigue disponible, fue publicada el 19 de Octubre. Si te interesa, escribe."}
    b = {"descripcion": "Linda propiedad. Sigue disponible, fue publicada el 24 de Octubre. Si te interesa, escribe."}
    assert d.hash_observacion(a) == d.hash_observacion(b)
    assert d.hash_observacion(a) != d.hash_observacion({"descripcion": "Linda propiedad. Arrendada."})
    # sin la frase, el hash es el mismo que antes del cambio (no genera observaciones nuevas)
    sin = {"precio": "450.000", "descripcion": "Depto luminoso"}
    assert d.hash_observacion(sin) == d.hashlib.sha256(d.json.dumps(sin, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def test_reglas_de_uso_responsable():
    """El User-Agent es de navegador (el identificado recibe una página sin precio, P-25) y el presupuesto diario tiene tope."""
    assert config.HEADERS["User-Agent"].startswith("Mozilla/5.0")
    assert d.PRESUPUESTO_24H <= 5000


class _Resp:
    def __init__(self, texto, url="https://www.portalinmobiliario.com/MLC-1-depto-_JM", status=200):
        self.text, self.url, self.status_code = texto, url, status


def _pagina(con_app_props: bool) -> str:
    estado = '{"appProps":{"pageProps":{"initialState":{"components":{"price":{"price":{"value":1}}}}}}}' if con_app_props \
        else '{"framework":{}}'
    url = "https://www.portalinmobiliario.com/MLC-1-depto-_JM"
    return (f'<html><head><link rel="canonical" href="{url}"><meta property="og:url" content="{url}"></head><body>'
            f"<script>_n.ctx.r={estado};_n.ctx.r.assets.manifest={{}}</script></body></html>")


def test_pagina_completa_es_ok(monkeypatch):
    monkeypatch.setattr(d.requests, "get", lambda *a, **k: _Resp(_pagina(True)))
    assert d.visitar("u", "MLC-1", "r")["resultado"] == "ok"


def test_pagina_reducida_sin_app_props_es_error(monkeypatch):
    """P-25: con ciertos User-Agent el portal responde 200 con el aviso correcto pero sin datos."""
    monkeypatch.setattr(d.requests, "get", lambda *a, **k: _Resp(_pagina(False)))
    r = d.visitar("u", "MLC-1", "r")
    assert r["resultado"] == "error" and "appProps" in r["detalle"]


def test_no_lanza_tandas_minusculas_al_borde_del_presupuesto():
    class BD:
        def ejecutar(self, fn, *a):
            assert fn is d.visitas_ultimas_24h, "no debe armar la cola ni visitar"
            return 4990
    assert d.ejecutar(BD(), 400, ["nuevo"], ["x"], presupuesto=5000) == ("presupuesto", 0)
