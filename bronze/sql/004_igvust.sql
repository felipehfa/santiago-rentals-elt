-- Índice de Vulnerabilidad Socioterritorial (IGVUST) por Unidad Vecinal, del Registro Social de Hogares.
-- Es una tabla de REFERENCIA ESTÁTICA, no una tabla de observaciones: se carga completa desde el shapefile
-- (bronze/cargar_igvust.py) y se reemplaza entera cada vez que se actualiza el archivo. Es la excepción
-- documentada a "Bronce solo inserta", igual que en el proyecto de Databricks.
-- Los polígonos se guardan como WKT en EPSG:4326 (el shapefile viene en EPSG:3857).

CREATE TABLE IF NOT EXISTS bronze.igvust_uv (
    uv_rsh          BIGINT PRIMARY KEY,       -- id de la Unidad Vecinal
    cod_com         INTEGER NOT NULL,
    comuna          TEXT NOT NULL,
    cod_reg         INTEGER NOT NULL,
    region          TEXT NOT NULL,
    rank_nac        INTEGER,                  -- ranking nacional de vulnerabilidad de la UV
    c_ig_com        INTEGER,                  -- cuartil del índice dentro de la comuna
    c_ig_reg        INTEGER,                  -- ... dentro de la región
    c_ig_nac        INTEGER,                  -- ... a nivel nacional
    pob_rsh_uv      NUMERIC,                  -- personas registradas en el RSH en la UV
    hog_uv          NUMERIC,                  -- hogares registrados en el RSH en la UV
    p_urbano        NUMERIC,                  -- proporción urbana de la UV
    geometria_wkt   TEXT NOT NULL,
    archivo_origen  TEXT NOT NULL,
    cargado_en      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS igvust_uv_comuna_idx ON bronze.igvust_uv (cod_com);
