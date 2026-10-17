-- Construye los dos SCD2 desde silver.aviso_observaciones con la técnica de "islas": se marca cada
-- observación que cambia respecto de la anterior del mismo aviso, y las observaciones consecutivas sin
-- cambio se juntan en un solo intervalo. Todo se deriva de las fechas REALES de observación y se puede
-- reconstruir completo, a diferencia de un SCD2 que se actualiza con UPDATE en cada corrida.

TRUNCATE gold.dim_estado_aviso_scd2;

INSERT INTO gold.dim_estado_aviso_scd2
    (id_aviso, valid_from, valid_to, is_current, estado_publicacion, estado_texto, ultima_confirmacion)
WITH marcadas AS (
    SELECT o.*,
           (o.estado_publicacion IS DISTINCT FROM
                LAG(o.estado_publicacion) OVER (PARTITION BY o.id_aviso ORDER BY o.observado_en, o.observacion_id)
           ) AS cambio
    FROM silver.aviso_observaciones o
),
islas AS (
    SELECT m.*,
           SUM(m.cambio::int) OVER (PARTITION BY m.id_aviso ORDER BY m.observado_en, m.observacion_id) AS isla
    FROM marcadas m
),
intervalos AS (
    SELECT id_aviso, isla,
           min(observado_en) AS valid_from,
           (array_agg(estado_publicacion ORDER BY observado_en, observacion_id))[1] AS estado_publicacion,
           (array_agg(estado_texto ORDER BY observado_en, observacion_id))[1] AS estado_texto
    FROM islas GROUP BY id_aviso, isla
),
con_fin AS (
    SELECT i.*, LEAD(i.valid_from) OVER (PARTITION BY i.id_aviso ORDER BY i.valid_from) AS valid_to
    FROM intervalos i
)
SELECT f.id_aviso, f.valid_from, f.valid_to, (f.valid_to IS NULL), f.estado_publicacion, f.estado_texto,
       CASE WHEN f.valid_to IS NULL THEN a.ultima_visita_detalle END
FROM con_fin f
LEFT JOIN silver.avisos a ON a.id_aviso = f.id_aviso;


TRUNCATE gold.dim_precio_aviso_scd2;

INSERT INTO gold.dim_precio_aviso_scd2
    (id_aviso, valid_from, valid_to, is_current, precio_valor, precio_moneda, precio_original, tiene_rebaja,
     precio_clp_observado, ultima_confirmacion)
WITH marcadas AS (
    SELECT o.*,
           ((o.precio_valor, o.precio_moneda, o.precio_original) IS DISTINCT FROM
                (LAG(o.precio_valor) OVER w, LAG(o.precio_moneda) OVER w, LAG(o.precio_original) OVER w)
           ) AS cambio
    FROM silver.aviso_observaciones o
    WINDOW w AS (PARTITION BY o.id_aviso ORDER BY o.observado_en, o.observacion_id)
),
islas AS (
    SELECT m.*,
           SUM(m.cambio::int) OVER (PARTITION BY m.id_aviso ORDER BY m.observado_en, m.observacion_id) AS isla
    FROM marcadas m
),
intervalos AS (
    SELECT id_aviso, isla,
           min(observado_en) AS valid_from,
           (array_agg(precio_valor ORDER BY observado_en, observacion_id))[1] AS precio_valor,
           (array_agg(precio_moneda ORDER BY observado_en, observacion_id))[1] AS precio_moneda,
           (array_agg(precio_original ORDER BY observado_en, observacion_id))[1] AS precio_original,
           (array_agg(precio_clp ORDER BY observado_en, observacion_id))[1] AS precio_clp_observado
    FROM islas GROUP BY id_aviso, isla
),
con_fin AS (
    SELECT i.*, LEAD(i.valid_from) OVER (PARTITION BY i.id_aviso ORDER BY i.valid_from) AS valid_to
    FROM intervalos i
)
SELECT f.id_aviso, f.valid_from, f.valid_to, (f.valid_to IS NULL), f.precio_valor, f.precio_moneda,
       f.precio_original, (f.precio_original IS NOT NULL), f.precio_clp_observado,
       CASE WHEN f.valid_to IS NULL THEN a.ultima_visita_detalle END
FROM con_fin f
LEFT JOIN silver.avisos a ON a.id_aviso = f.id_aviso;
