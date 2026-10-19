-- Reconstruye silver.avisos completa desde Bronce. Se ejecuta dentro de una transacción (ver
-- construir_silver.py): si algo falla, la tabla anterior queda intacta.
--
-- Umbrales de las banderas de calidad: PROVISIONALES. Se copiaron de Concepción o son holguras propias y
-- hay que revisarlos con los datos de la Región Metropolitana (ver docs/01, sección 6):
--   coordenadas   caja generosa de la RM: lat -34,4 a -32,9 y lon -71,8 a -69,7
--   conteos       dormitorios > 6, baños > 5, estacionamientos > 15 (Concepción)
--   superficie    útil < 12 o > 500 m2 (propio; el umbral de 30 m2 de Concepción NO se usa: en Santiago
--                 el 28 % de los avisos tiene 30 m2 o menos)
--   precio        precio_clp > 8.000.000 (Concepción) o < 100.000 (propio)
--   precio_m2     costo total por m2 útil con z robusto (MAD) > 5 respecto de la mediana de su comuna (propio)
--   POI           radio de 500 m (Concepción)

TRUNCATE silver.avisos;

INSERT INTO silver.avisos (
    id_aviso, comuna, tipo_propiedad, operacion, url, titulo, ubicacion,
    primera_vez_visto, ultima_vez_visto, fuera_de_grilla, es_proyecto, tiene_detalle, ultima_visita_detalle,
    estado_texto, estado_publicacion,
    precio_valor, precio_moneda, precio_original, tiene_rebaja, precio_grilla, moneda_grilla,
    fecha_precio, valor_uf, valor_dolar, precio_clp, precio_original_clp, gastos_comunes, costo_total_clp,
    dormitorios, banos, estacionamientos, bodegas, tiene_bodega,
    superficie_total_m2, superficie_util_m2, superficie_grilla_m2,
    antiguedad_anos, piso_unidad, deptos_por_piso, max_habitantes,
    amoblado, admite_mascotas, condominio_cerrado, estacionamiento_visitas, solo_familias,
    piscina, quincho, conserjeria, ascensor,
    latitud, longitud, barrio, descripcion,
    fecha_publicacion_texto, fecha_publicacion_aprox, fecha_publicacion_precision,
    cantidad_paraderos, distancia_min_m_paraderos,
    cantidad_estaciones_metro, distancia_min_m_estaciones_metro,
    cantidad_jardines_infantiles, distancia_min_m_jardines_infantiles,
    cantidad_colegios, distancia_min_m_colegios,
    cantidad_universidades, distancia_min_m_universidades,
    cantidad_plazas, distancia_min_m_plazas,
    cantidad_supermercados, distancia_min_m_supermercados,
    cantidad_farmacias, distancia_min_m_farmacias,
    cantidad_centros_comerciales, distancia_min_m_centros_comerciales,
    cantidad_hospitales, distancia_min_m_hospitales,
    cantidad_clinicas, distancia_min_m_clinicas,
    sin_coordenadas, coordenada_fuera_de_region, conteo_imposible, superficie_util_sospechosa,
    precio_sospechoso, gastos_comunes_faltante, moneda_sin_valor
)
WITH
-- Última versión de la tarjeta de la grilla.
card AS (
    SELECT DISTINCT ON (id_aviso) id_aviso, comuna, tipo_propiedad, operacion, payload
    FROM bronze.grilla_avisos ORDER BY id_aviso, scraped_at DESC
),
-- Última observación del detalle, y la primera (de ahí sale la fecha de publicación, porque el texto
-- relativo es más fiable cuanto más cerca de su publicación se lee).
det AS (
    SELECT DISTINCT ON (id_aviso) * FROM bronze.detalle_avisos ORDER BY id_aviso, scraped_at DESC
),
det_primera AS (
    SELECT DISTINCT ON (id_aviso) id_aviso, scraped_at,
           payload->>'fecha_publicacion_texto' AS texto
    FROM bronze.detalle_avisos ORDER BY id_aviso, scraped_at ASC
),
visita AS (
    SELECT id_aviso,
           max(scraped_at) FILTER (WHERE resultado = 'ok') AS ultima_ok,
           bool_or(resultado = 'proyecto') AS proyecto_confirmado
    FROM bronze.detalle_intentos GROUP BY id_aviso
),
cob AS (
    SELECT comuna, max(run_id) AS rid FROM bronze.grilla_cobertura WHERE estado = 'completa' GROUP BY comuna
),
base AS (
    SELECT
        gv.id_aviso, card.comuna, card.tipo_propiedad, card.operacion,
        card.payload AS tarjeta, det.payload AS d, det.payload->'poi_crudo' AS poi,
        gv.primera_vez, gv.ultima_vez,
        (cob.rid IS NOT NULL AND gv.ultimo_run_id < cob.rid) AS fuera_de_grilla,
        (COALESCE(visita.proyecto_confirmado, false)
            OR card.payload->>'texto_tarjeta' ~* '(unidades? disponibles?|^proyecto )') AS es_proyecto,
        (det.id_aviso IS NOT NULL) AS tiene_detalle,
        visita.ultima_ok,
        (visita.ultima_ok AT TIME ZONE 'America/Santiago')::date AS fecha_precio,
        det.estado_texto, det.precio_valor, det.precio_moneda, det.precio_original,
        (det_primera.scraped_at AT TIME ZONE 'America/Santiago')::date AS fecha_primera_obs,
        det_primera.texto AS fecha_texto
    FROM bronze.grilla_vistos gv
    JOIN card ON card.id_aviso = gv.id_aviso
    LEFT JOIN cob ON cob.comuna = card.comuna
    LEFT JOIN visita ON visita.id_aviso = gv.id_aviso
    LEFT JOIN det ON det.id_aviso = gv.id_aviso
    LEFT JOIN det_primera ON det_primera.id_aviso = gv.id_aviso
),
-- UF y dólar del día de la última visita; si ese día no hay valor (el dólar no publica fines de semana)
-- se usa el anterior más cercano, hasta 5 días atrás. Más lejos que eso queda NULL y se marca.
conv AS (
    SELECT b.*,
           uf.valor AS valor_uf, usd.valor AS valor_dolar
    FROM base b
    LEFT JOIN LATERAL (
        SELECT valor FROM silver.indicadores_diarios
        WHERE indicador = 'uf' AND fecha <= b.fecha_precio AND fecha >= b.fecha_precio - 5
        ORDER BY fecha DESC LIMIT 1) uf ON TRUE
    LEFT JOIN LATERAL (
        SELECT valor FROM silver.indicadores_diarios
        WHERE indicador = 'dolar' AND fecha <= b.fecha_precio AND fecha >= b.fecha_precio - 5
        ORDER BY fecha DESC LIMIT 1) usd ON TRUE
),
calc AS (
    SELECT c.*,
           CASE c.precio_moneda WHEN 'CLP' THEN c.precio_valor
                                WHEN 'CLF' THEN c.precio_valor * c.valor_uf
                                WHEN 'USD' THEN c.precio_valor * c.valor_dolar END AS precio_clp,
           CASE c.precio_moneda WHEN 'CLP' THEN c.precio_original
                                WHEN 'CLF' THEN c.precio_original * c.valor_uf
                                WHEN 'USD' THEN c.precio_original * c.valor_dolar END AS precio_original_clp,
           silver.gastos_comunes(c.d->>'gastos_comunes') AS gastos_comunes,
           silver.num_plano(c.d->>'latitud') AS latitud,
           silver.num_plano(c.d->>'longitud') AS longitud,
           silver.num_chileno(c.d->>'superficie_util_m2') AS sup_util,
           silver.num_chileno(c.d->>'dormitorios')::int AS dormitorios,
           silver.num_chileno(c.d->>'banos')::int AS banos,
           silver.num_chileno(c.d->>'estacionamientos')::int AS estacionamientos
    FROM conv c
)
SELECT
    k.id_aviso, k.comuna, k.tipo_propiedad, k.operacion,
    k.tarjeta->>'url', k.tarjeta->>'titulo', k.tarjeta->>'ubicacion',
    k.primera_vez, k.ultima_vez, k.fuera_de_grilla, k.es_proyecto, k.tiene_detalle, k.ultima_ok,
    k.estado_texto,
    CASE WHEN NOT k.tiene_detalle THEN NULL
         WHEN k.estado_texto IS NULL THEN 'activo'
         WHEN lower(k.estado_texto) LIKE '%finaliz%' THEN 'finalizado'
         WHEN lower(k.estado_texto) LIKE '%pausad%' THEN 'pausado'
         ELSE 'otro' END,
    k.precio_valor, k.precio_moneda, k.precio_original,
    CASE WHEN k.tiene_detalle THEN k.precio_original IS NOT NULL END,
    silver.num_chileno(k.tarjeta->>'precio'),
    CASE k.tarjeta->>'moneda' WHEN '$' THEN 'CLP' WHEN 'UF' THEN 'CLF' WHEN 'US$' THEN 'USD' END,
    k.fecha_precio, k.valor_uf, k.valor_dolar, k.precio_clp, k.precio_original_clp, k.gastos_comunes,
    CASE WHEN k.precio_clp IS NOT NULL THEN k.precio_clp + COALESCE(k.gastos_comunes, 0) END,
    k.dormitorios, k.banos, k.estacionamientos,
    -- 242085 es un código interno del sitio (el mismo que usa en sus filtros "Sí"): significa "tiene bodega"
    -- sin decir cuántas. Un conteo mayor a 20 se descarta; el resto es la cantidad real.
    CASE WHEN silver.num_chileno(k.d->>'bodegas') BETWEEN 0 AND 20
         THEN silver.num_chileno(k.d->>'bodegas')::int END,
    CASE WHEN k.d->>'bodegas' = '242085' THEN true
         WHEN silver.num_chileno(k.d->>'bodegas') BETWEEN 0 AND 20 THEN silver.num_chileno(k.d->>'bodegas') > 0 END,
    silver.num_chileno(k.d->>'superficie_total_m2'), k.sup_util,
    silver.num_chileno(k.tarjeta->>'superficie_m2'),
    silver.num_chileno(k.d->>'antiguedad_anos')::int, silver.num_chileno(k.d->>'piso_unidad')::int,
    silver.num_chileno(k.d->>'deptos_por_piso')::int, silver.num_chileno(k.d->>'max_habitantes')::int,
    silver.si_no(k.d->>'amoblado'), silver.si_no(k.d->>'admite_mascotas'), silver.si_no(k.d->>'condominio_cerrado'),
    silver.si_no(k.d->>'estacionamiento_visitas'), silver.si_no(k.d->>'solo_familias'),
    silver.si_no(k.d->>'piscina'), silver.si_no(k.d->>'quincho'), silver.si_no(k.d->>'conserjeria'),
    silver.si_no(k.d->>'ascensor'),
    k.latitud, k.longitud, k.d->>'barrio', k.d->>'descripcion',
    k.fecha_texto,
    silver.fecha_publicacion(k.fecha_texto, k.fecha_primera_obs),
    silver.fecha_publicacion_precision(k.fecha_texto),
    silver.poi_cantidad(k.poi->'paraderos', 500),            silver.poi_distancia_min(k.poi->'paraderos', 500),
    silver.poi_cantidad(k.poi->'estaciones_metro', 500),     silver.poi_distancia_min(k.poi->'estaciones_metro', 500),
    silver.poi_cantidad(k.poi->'jardines_infantiles', 500),  silver.poi_distancia_min(k.poi->'jardines_infantiles', 500),
    silver.poi_cantidad(k.poi->'colegios', 500),             silver.poi_distancia_min(k.poi->'colegios', 500),
    silver.poi_cantidad(k.poi->'universidades', 500),        silver.poi_distancia_min(k.poi->'universidades', 500),
    silver.poi_cantidad(k.poi->'plazas', 500),               silver.poi_distancia_min(k.poi->'plazas', 500),
    silver.poi_cantidad(k.poi->'supermercados', 500),        silver.poi_distancia_min(k.poi->'supermercados', 500),
    silver.poi_cantidad(k.poi->'farmacias', 500),            silver.poi_distancia_min(k.poi->'farmacias', 500),
    silver.poi_cantidad(k.poi->'centros_comerciales', 500),  silver.poi_distancia_min(k.poi->'centros_comerciales', 500),
    silver.poi_cantidad(k.poi->'hospitales', 500),           silver.poi_distancia_min(k.poi->'hospitales', 500),
    silver.poi_cantidad(k.poi->'clinicas', 500),             silver.poi_distancia_min(k.poi->'clinicas', 500),
    -- banderas de calidad (NULL cuando no hay detalle: no hay nada que evaluar)
    CASE WHEN k.tiene_detalle THEN (k.latitud IS NULL OR k.longitud IS NULL) END,
    CASE WHEN k.latitud IS NOT NULL AND k.longitud IS NOT NULL
         THEN NOT (k.latitud BETWEEN -34.4 AND -32.9 AND k.longitud BETWEEN -71.8 AND -69.7) END,
    CASE WHEN k.tiene_detalle THEN (k.dormitorios > 6 OR k.banos > 5 OR k.estacionamientos > 15) END,
    CASE WHEN k.sup_util IS NOT NULL THEN (k.sup_util < 12 OR k.sup_util > 500) END,
    CASE WHEN k.precio_clp IS NOT NULL THEN (k.precio_clp > 8000000 OR k.precio_clp < 100000) END,
    CASE WHEN k.tiene_detalle THEN k.gastos_comunes IS NULL END,
    CASE WHEN k.tiene_detalle THEN
         (k.precio_moneda = 'CLF' AND k.valor_uf IS NULL) OR (k.precio_moneda = 'USD' AND k.valor_dolar IS NULL) END
FROM calc k;

-- precio_m2_atipico: segunda pasada, porque depende de la mediana de cada comuna. Mide el costo total por m2
-- útil en logaritmo y lo compara con la mediana de su comuna usando MAD (desviación absoluta mediana), que no se
-- deja arrastrar por los propios atípicos. z robusto = 0,6745 * |x - mediana| / MAD; se marca con z > 5, un corte
-- deliberadamente holgado para no tocar propiedades caras legítimas (PROVISIONAL, revisar a mano una muestra).
-- Comunas con menos de 30 avisos usan la mediana y el MAD de toda la región; el MAD tiene un piso de 0,05.
-- Se calcula solo con avisos con detalle, superficie útil >= 12 m2, no proyectos y sin precio sospechoso.
WITH base AS (
    SELECT comuna, ln(costo_total_clp / superficie_util_m2) AS lm
    FROM silver.avisos
    WHERE tiene_detalle AND NOT es_proyecto AND costo_total_clp > 0 AND superficie_util_m2 >= 12
      AND NOT COALESCE(superficie_util_sospechosa, false) AND NOT COALESCE(precio_sospechoso, false)
),
global_med AS (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY lm) AS med FROM base),
global_mad AS (
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(b.lm - g.med)) AS mad FROM base b, global_med g
),
comuna_med AS (
    SELECT comuna, count(*) AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY lm) AS med FROM base GROUP BY comuna
),
comuna_mad AS (
    SELECT b.comuna, percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(b.lm - c.med)) AS mad
    FROM base b JOIN comuna_med c USING (comuna) GROUP BY b.comuna
),
stats AS (
    SELECT c.comuna,
           CASE WHEN c.n >= 30 THEN c.med ELSE g.med END AS med,
           GREATEST(CASE WHEN c.n >= 30 THEN m.mad ELSE gm.mad END, 0.05) AS mad
    FROM comuna_med c JOIN comuna_mad m USING (comuna), global_med g, global_mad gm
)
UPDATE silver.avisos a
SET precio_m2_atipico =
    0.6745 * abs(ln(a.costo_total_clp / a.superficie_util_m2) - s.med) / s.mad > 5
FROM stats s
WHERE a.comuna = s.comuna AND a.tiene_detalle AND a.costo_total_clp > 0 AND a.superficie_util_m2 > 0;

UPDATE silver.avisos SET construido_en = now();
