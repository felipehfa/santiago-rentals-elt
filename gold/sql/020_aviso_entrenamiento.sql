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

TRUNCATE gold.aviso_entrenamiento;

INSERT INTO gold.aviso_entrenamiento (
    id_aviso, comuna, barrio, apto_entrenamiento, motivo_exclusion,
    estado_publicacion, fecha_publicacion_aprox, fecha_publicacion_precision, primera_vez_visto, ultima_vez_visto,
    dias_en_mercado, n_cambios_estado, n_cambios_precio,
    precio_valor, precio_moneda, tiene_rebaja, fecha_precio, precio_clp, gastos_comunes,
    costo_total_clp, costo_total_uf, gastos_comunes_faltante,
    dormitorios, banos, estacionamientos, bodegas, tiene_bodega, superficie_total_m2, superficie_util_m2,
    antiguedad_anos, piso_unidad, deptos_por_piso,
    amoblado, admite_mascotas, condominio_cerrado, estacionamiento_visitas, piscina, quincho, conserjeria, ascensor,
    latitud, longitud,
    cantidad_paraderos, distancia_min_m_paraderos, cantidad_estaciones_metro, distancia_min_m_estaciones_metro,
    cantidad_jardines_infantiles, distancia_min_m_jardines_infantiles, cantidad_colegios, distancia_min_m_colegios,
    cantidad_universidades, distancia_min_m_universidades, cantidad_plazas, distancia_min_m_plazas,
    cantidad_supermercados, distancia_min_m_supermercados, cantidad_farmacias, distancia_min_m_farmacias,
    cantidad_centros_comerciales, distancia_min_m_centros_comerciales, cantidad_hospitales, distancia_min_m_hospitales,
    cantidad_clinicas, distancia_min_m_clinicas,
    uv_rsh, rank_nac, c_ig_com, c_ig_reg, c_ig_nac, pob_rsh_uv, hog_uv, p_urbano
)
WITH cambios AS (
    SELECT id_aviso, count(*) - 1 AS n FROM gold.dim_estado_aviso_scd2 GROUP BY id_aviso
),
cambios_precio AS (
    SELECT id_aviso, count(*) - 1 AS n FROM gold.dim_precio_aviso_scd2 GROUP BY id_aviso
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
               CASE WHEN a.precio_sospechoso THEN 'precio_sospechoso' END
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
    m.antiguedad_anos, m.piso_unidad, m.deptos_por_piso,
    m.amoblado, m.admite_mascotas, m.condominio_cerrado, m.estacionamiento_visitas, m.piscina, m.quincho,
    m.conserjeria, m.ascensor,
    m.latitud, m.longitud,
    m.cantidad_paraderos, m.distancia_min_m_paraderos, m.cantidad_estaciones_metro, m.distancia_min_m_estaciones_metro,
    m.cantidad_jardines_infantiles, m.distancia_min_m_jardines_infantiles, m.cantidad_colegios, m.distancia_min_m_colegios,
    m.cantidad_universidades, m.distancia_min_m_universidades, m.cantidad_plazas, m.distancia_min_m_plazas,
    m.cantidad_supermercados, m.distancia_min_m_supermercados, m.cantidad_farmacias, m.distancia_min_m_farmacias,
    m.cantidad_centros_comerciales, m.distancia_min_m_centros_comerciales, m.cantidad_hospitales,
    m.distancia_min_m_hospitales, m.cantidad_clinicas, m.distancia_min_m_clinicas,
    m.uv_rsh, m.rank_nac, m.c_ig_com, m.c_ig_reg, m.c_ig_nac, m.pob_rsh_uv, m.hog_uv, m.p_urbano
FROM motivos m
LEFT JOIN cambios ON cambios.id_aviso = m.id_aviso
LEFT JOIN cambios_precio ON cambios_precio.id_aviso = m.id_aviso;

UPDATE gold.aviso_entrenamiento SET construido_en = now();
