-- Reconstruye gold.aviso_entrenamiento desde silver.avisos y los SCD2 de Gold (que deben construirse antes).
--
-- Regla de aptitud (decisión del 17-oct-2026): un aviso entra al entrenamiento si NO tiene ningún motivo de
-- exclusión. Los motivos se acumulan en motivo_exclusion (separados por coma) para poder revisar qué descarta
-- más filas y cambiar la regla sin reprocesar nada.
--
-- Umbrales provisionales (revisar con más datos):
--   finalizados  solo entran si su fecha de publicación es de los últimos 90 días. Un finalizado sin
--                fecha de publicación queda fuera: no se sabe qué tan viejo es su precio (criterio de Concepción)
--   superficie   la bandera superficie_util_sospechosa viene de Silver (< 12 o > 500 m2)
--   precio       la bandera precio_sospechoso viene de Silver (> 8.000.000 o < 100.000 CLP)
--   precio_m2    la bandera precio_m2_atipico viene de Silver (costo por m2 con z robusto > 5 en su comuna)
--
-- Antigüedad (decisión del 21-oct-2026): si el aviso no la trae o trae un valor imposible (fuera de 0 a 150 años), se
-- completa con la mediana de los avisos con dato válido en el mismo punto (5 decimales: un edificio) y, si no hay,
-- con la de los avisos a menos de ~150 m (al menos 3). Medido con un aviso a la vez: error mediano de 1 año en el mismo
-- punto; 5,3 años de error medio con vecinos (7,8 con la mediana global). antiguedad_origen dice de dónde salió el valor.

TRUNCATE gold.aviso_entrenamiento;

INSERT INTO gold.aviso_entrenamiento (
    id_aviso, comuna, barrio, apto_entrenamiento, motivo_exclusion,
    estado_publicacion, fecha_publicacion_aprox, fecha_publicacion_precision, primera_vez_visto, ultima_vez_visto,
    dias_en_mercado, n_cambios_estado, n_cambios_precio,
    precio_valor, precio_moneda, tiene_rebaja, fecha_precio, precio_clp, gastos_comunes,
    costo_total_clp, costo_total_uf, gastos_comunes_faltante,
    dormitorios, banos, estacionamientos, bodegas, tiene_bodega, superficie_total_m2, superficie_util_m2,
    antiguedad_anos, antiguedad_origen, piso_unidad, deptos_por_piso,
    amoblado, admite_mascotas, condominio_cerrado, estacionamiento_visitas, piscina, quincho, conserjeria, ascensor,
    latitud, longitud,
    cantidad_paraderos, distancia_min_m_paraderos, cantidad_estaciones_metro, distancia_min_m_estaciones_metro,
    cantidad_jardines_infantiles, distancia_min_m_jardines_infantiles, cantidad_colegios, distancia_min_m_colegios,
    cantidad_universidades, distancia_min_m_universidades, cantidad_plazas, distancia_min_m_plazas,
    cantidad_supermercados, distancia_min_m_supermercados, cantidad_farmacias, distancia_min_m_farmacias,
    cantidad_centros_comerciales, distancia_min_m_centros_comerciales, cantidad_hospitales, distancia_min_m_hospitales,
    cantidad_clinicas, distancia_min_m_clinicas,
    uv_rsh, rank_nac, c_ig_com, c_ig_reg, c_ig_nac, pob_rsh_uv, hog_uv, p_urbano,
    titulo, descripcion, url
)
WITH cambios AS (
    SELECT id_aviso, count(*) - 1 AS n FROM gold.dim_estado_aviso_scd2 GROUP BY id_aviso
),
cambios_precio AS (
    SELECT id_aviso, count(*) - 1 AS n FROM gold.dim_precio_aviso_scd2 GROUP BY id_aviso
),
edad_valida AS (
    SELECT latitud::numeric AS lat, longitud::numeric AS lon, antiguedad_anos AS edad,
           floor(latitud / 0.0015)::int AS cy, floor(longitud / 0.0018)::int AS cx
    FROM silver.avisos
    WHERE latitud IS NOT NULL AND longitud IS NOT NULL AND antiguedad_anos BETWEEN 0 AND 150
),
edad_punto AS (
    SELECT round(lat, 5) AS la, round(lon, 5) AS lo, percentile_cont(0.5) WITHIN GROUP (ORDER BY edad) AS mediana
    FROM edad_valida GROUP BY 1, 2
),
a_completar AS (
    SELECT id_aviso, latitud::numeric AS lat, longitud::numeric AS lon,
           floor(latitud / 0.0015)::int AS cy, floor(longitud / 0.0018)::int AS cx
    FROM silver.avisos
    WHERE latitud IS NOT NULL AND longitud IS NOT NULL
      AND (antiguedad_anos IS NULL OR antiguedad_anos NOT BETWEEN 0 AND 150)
),
edad_vecinos AS (
    SELECT c.id_aviso, percentile_cont(0.5) WITHIN GROUP (ORDER BY v.edad) AS mediana
    FROM a_completar c
    JOIN edad_valida v ON v.cy BETWEEN c.cy - 1 AND c.cy + 1 AND v.cx BETWEEN c.cx - 1 AND c.cx + 1
                      AND abs(v.lat - c.lat) < 0.00135 AND abs(v.lon - c.lon) < 0.0016
    GROUP BY c.id_aviso HAVING count(*) >= 3
),
motivos AS (
    SELECT a.*,
           array_remove(ARRAY[
               CASE WHEN a.es_proyecto THEN 'proyecto' END,
               CASE WHEN NOT a.tiene_detalle THEN 'sin_detalle' END,
               CASE WHEN a.estado_publicacion = 'otro' THEN 'estado_no_reconocido' END,
               CASE WHEN a.estado_publicacion = 'finalizado'
                         AND (a.fecha_publicacion_aprox IS NULL
                              OR a.fecha_publicacion_aprox < current_date - 90) THEN 'finalizado_antiguo' END,
               CASE WHEN a.tiene_detalle AND a.costo_total_clp IS NULL THEN 'sin_precio' END,
               CASE WHEN a.tiene_detalle AND a.superficie_util_m2 IS NULL AND a.superficie_total_m2 IS NULL
                    THEN 'sin_superficie' END,
               CASE WHEN a.sin_coordenadas THEN 'sin_coordenadas' END,
               CASE WHEN a.coordenada_fuera_de_region THEN 'coordenada_fuera_de_region' END,
               CASE WHEN a.conteo_imposible THEN 'conteo_imposible' END,
               CASE WHEN a.superficie_util_sospechosa THEN 'superficie_sospechosa' END,
               CASE WHEN a.precio_sospechoso THEN 'precio_sospechoso' END,
               CASE WHEN a.precio_m2_atipico THEN 'precio_m2_atipico' END
           ], NULL) AS lista_motivos
    FROM silver.avisos a
)
SELECT
    m.id_aviso, m.comuna, m.barrio,
    cardinality(m.lista_motivos) = 0,
    NULLIF(array_to_string(m.lista_motivos, ','), ''),
    m.estado_publicacion, m.fecha_publicacion_aprox, m.fecha_publicacion_precision,
    m.primera_vez_visto, m.ultima_vez_visto,
    CASE WHEN m.fecha_publicacion_aprox IS NOT NULL
         THEN ((m.ultima_vez_visto AT TIME ZONE 'America/Santiago')::date - m.fecha_publicacion_aprox) END,
    cambios.n, cambios_precio.n,
    m.precio_valor, m.precio_moneda, m.tiene_rebaja, m.fecha_precio, m.precio_clp, m.gastos_comunes,
    m.costo_total_clp,
    CASE WHEN m.valor_uf IS NOT NULL AND m.costo_total_clp IS NOT NULL THEN m.costo_total_clp / m.valor_uf END,
    m.gastos_comunes_faltante,
    m.dormitorios, m.banos, m.estacionamientos, m.bodegas, m.tiene_bodega, m.superficie_total_m2, m.superficie_util_m2,
    CASE WHEN m.antiguedad_anos BETWEEN 0 AND 150 THEN m.antiguedad_anos
         ELSE round(coalesce(ep.mediana, ev.mediana))::int END,
    CASE WHEN m.antiguedad_anos BETWEEN 0 AND 150 THEN 'aviso'
         WHEN ep.mediana IS NOT NULL THEN 'mismo_punto'
         WHEN ev.mediana IS NOT NULL THEN 'vecinos'
         ELSE 'sin_dato' END,
    m.piso_unidad, m.deptos_por_piso,
    m.amoblado, m.admite_mascotas, m.condominio_cerrado, m.estacionamiento_visitas, m.piscina, m.quincho,
    m.conserjeria, m.ascensor,
    m.latitud, m.longitud,
    m.cantidad_paraderos, m.distancia_min_m_paraderos, m.cantidad_estaciones_metro, m.distancia_min_m_estaciones_metro,
    m.cantidad_jardines_infantiles, m.distancia_min_m_jardines_infantiles, m.cantidad_colegios, m.distancia_min_m_colegios,
    m.cantidad_universidades, m.distancia_min_m_universidades, m.cantidad_plazas, m.distancia_min_m_plazas,
    m.cantidad_supermercados, m.distancia_min_m_supermercados, m.cantidad_farmacias, m.distancia_min_m_farmacias,
    m.cantidad_centros_comerciales, m.distancia_min_m_centros_comerciales, m.cantidad_hospitales,
    m.distancia_min_m_hospitales, m.cantidad_clinicas, m.distancia_min_m_clinicas,
    m.uv_rsh, m.rank_nac, m.c_ig_com, m.c_ig_reg, m.c_ig_nac, m.pob_rsh_uv, m.hog_uv, m.p_urbano,
    m.titulo, m.descripcion, m.url
FROM motivos m
LEFT JOIN cambios ON cambios.id_aviso = m.id_aviso
LEFT JOIN cambios_precio ON cambios_precio.id_aviso = m.id_aviso
LEFT JOIN edad_punto ep ON ep.la = round(m.latitud::numeric, 5) AND ep.lo = round(m.longitud::numeric, 5)
LEFT JOIN edad_vecinos ev ON ev.id_aviso = m.id_aviso;

UPDATE gold.aviso_entrenamiento SET construido_en = now();
