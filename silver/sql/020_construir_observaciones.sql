-- Reconstruye silver.aviso_observaciones desde bronze.detalle_avisos. Se ejecuta dentro de la misma
-- transacción que 010_construir_avisos.sql (ver construir_silver.py).
--
-- Regla de conversión de monedas (decisión acordada el 17-oct-2026): UF y dólar al valor del día en que se
-- OBSERVÓ el precio, no al de la publicación. Si ese día no hay valor (el dólar no publica fines de semana)
-- se usa el anterior más cercano, hasta 5 días atrás; más lejos queda NULL y se marca moneda_sin_valor.

TRUNCATE silver.aviso_observaciones;

INSERT INTO silver.aviso_observaciones (
    observacion_id, id_aviso, observado_en, fecha_observacion, motivo_visita,
    estado_texto, estado_publicacion,
    precio_valor, precio_moneda, precio_original, tiene_rebaja,
    valor_uf, valor_dolar, precio_clp, precio_original_clp, gastos_comunes, costo_total_clp, moneda_sin_valor
)
SELECT
    d.id, d.id_aviso, d.scraped_at, o.fecha, d.motivo_visita,
    d.estado_texto,
    CASE WHEN d.estado_texto IS NULL THEN 'activo'
         WHEN lower(d.estado_texto) LIKE '%finaliz%' THEN 'finalizado'
         WHEN lower(d.estado_texto) LIKE '%pausad%' THEN 'pausado'
         ELSE 'otro' END,
    d.precio_valor, d.precio_moneda, d.precio_original, (d.precio_original IS NOT NULL),
    uf.valor, usd.valor,
    c.precio_clp, c.precio_original_clp, g.gastos,
    CASE WHEN c.precio_clp IS NOT NULL THEN c.precio_clp + COALESCE(g.gastos, 0) END,
    ((d.precio_moneda = 'CLF' AND uf.valor IS NULL) OR (d.precio_moneda = 'USD' AND usd.valor IS NULL))
FROM bronze.detalle_avisos d
CROSS JOIN LATERAL (SELECT (d.scraped_at AT TIME ZONE 'America/Santiago')::date AS fecha) o
LEFT JOIN LATERAL (
    SELECT valor FROM silver.indicadores_diarios
    WHERE indicador = 'uf' AND fecha <= o.fecha AND fecha >= o.fecha - 5
    ORDER BY fecha DESC LIMIT 1) uf ON TRUE
LEFT JOIN LATERAL (
    SELECT valor FROM silver.indicadores_diarios
    WHERE indicador = 'dolar' AND fecha <= o.fecha AND fecha >= o.fecha - 5
    ORDER BY fecha DESC LIMIT 1) usd ON TRUE
CROSS JOIN LATERAL (SELECT silver.gastos_comunes(d.payload->>'gastos_comunes') AS gastos) g
CROSS JOIN LATERAL (
    SELECT CASE d.precio_moneda WHEN 'CLP' THEN d.precio_valor
                                WHEN 'CLF' THEN d.precio_valor * uf.valor
                                WHEN 'USD' THEN d.precio_valor * usd.valor END AS precio_clp,
           CASE d.precio_moneda WHEN 'CLP' THEN d.precio_original
                                WHEN 'CLF' THEN d.precio_original * uf.valor
                                WHEN 'USD' THEN d.precio_original * usd.valor END AS precio_original_clp) c;

UPDATE silver.aviso_observaciones SET construido_en = now();
