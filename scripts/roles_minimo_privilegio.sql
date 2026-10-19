-- Roles de mínimo privilegio para santiago-rentals (BORRADOR: no se ha aplicado).
-- Aplicar a mano, con el rol dueño, en el SQL Editor de Supabase. Reemplazar <CLAVE_...> por claves
-- largas y aleatorias (sin @ : / # ni espacios); no versionar las claves reales.
-- Requisito: gold.predicciones debe existir (la crea gold/construir_gold.py vía gold/sql/001_schema.sql).
--
--   scraper_local  Scrapers de grilla y detalle: lee y escribe SOLO en bronze. Sin DDL.
--   ml_lectura     Entrenamiento, registro, gate y CI: SELECT sobre gold.aviso_entrenamiento y nada más.
--   ml_scoring     Scoring por lotes: SELECT sobre gold.aviso_entrenamiento e INSERT en gold.predicciones.
--
-- Silver y Gold se siguen construyendo con el rol dueño, solo desde local. Las reconstrucciones de Gold usan
-- TRUNCATE (no DROP), así que estos permisos sobreviven; gold.predicciones no se vacía nunca.

-- ── scraper_local ────────────────────────────────────────────────────────────
CREATE ROLE scraper_local LOGIN PASSWORD '<CLAVE_SCRAPER_LOCAL>';
GRANT USAGE ON SCHEMA bronze TO scraper_local;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA bronze TO scraper_local;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA bronze TO scraper_local;   -- ids autogenerados (runs, intentos)

-- Tablas y secuencias que se creen después en bronze (las crea el dueño)
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze GRANT SELECT, INSERT, UPDATE ON TABLES TO scraper_local;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze GRANT USAGE, SELECT ON SEQUENCES TO scraper_local;

-- ── ml_lectura ───────────────────────────────────────────────────────────────
CREATE ROLE ml_lectura LOGIN PASSWORD '<CLAVE_ML_LECTURA>';
GRANT USAGE ON SCHEMA gold TO ml_lectura;
GRANT SELECT ON gold.aviso_entrenamiento TO ml_lectura;

-- ── ml_scoring ───────────────────────────────────────────────────────────────
-- Solo INSERT en predicciones: no actualiza ni borra. La columna id_prediccion es IDENTITY, que no
-- necesita permisos sobre secuencias.
CREATE ROLE ml_scoring LOGIN PASSWORD '<CLAVE_ML_SCORING>';
GRANT USAGE ON SCHEMA gold TO ml_scoring;
GRANT SELECT ON gold.aviso_entrenamiento TO ml_scoring;
GRANT INSERT ON gold.predicciones TO ml_scoring;

-- Fuera de lo que se concede, los tres roles quedan sin acceso al resto de bronze/silver/gold.

-- ── Comprobación (ejecutar cada una conectado como el rol correspondiente) ──────
--   scraper_local:  select count(*) from bronze.runs;              -- debe funcionar
--                   select count(*) from silver.avisos;            -- debe fallar: permission denied
--                   drop table bronze.runs;                        -- debe fallar
--   ml_lectura:     select count(*) from gold.aviso_entrenamiento; -- debe funcionar
--                   select count(*) from bronze.runs;              -- debe fallar
--                   delete from gold.aviso_entrenamiento;          -- debe fallar
--   ml_scoring:     select count(*) from gold.aviso_entrenamiento; -- debe funcionar
--                   insert into gold.predicciones (id_aviso, modelo_nombre, modelo_version, costo_total_predicho_clp)
--                     values ('prueba', 'prueba', 0, 0);           -- debe funcionar (luego borrar con el dueño)
--                   select * from gold.predicciones;               -- debe fallar: sin SELECT
