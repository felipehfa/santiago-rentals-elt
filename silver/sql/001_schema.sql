-- Capa Silver: Bronce tipado, normalizado y marcado. Silver NO descarta filas: lo dudoso queda en columnas
-- de calidad (flags) y es Gold quien decide qué filas entran al entrenamiento.
-- Las tablas son derivadas y reconstruibles desde Bronce (ver 010_construir_avisos.sql). Este archivo es
-- idempotente: se re-aplica completo con silver/construir_silver.py.

CREATE SCHEMA IF NOT EXISTS silver;

-- ---------------------------------------------------------------------------------------------------------
-- Funciones de parseo. Viven en la base para que el SQL de construcción se lea sin regex repetidas.
-- ---------------------------------------------------------------------------------------------------------

-- Número con punto decimal estándar ('-33.38821'); NULL si no tiene esa forma.
CREATE OR REPLACE FUNCTION silver.num_plano(t text) RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN btrim(t) ~ '^-?\d+(\.\d+)?$' THEN btrim(t)::numeric END
$$;

-- Número en formato chileno: '.' separa miles y ',' es el decimal ('1.234,5' -> 1234.5).
CREATE OR REPLACE FUNCTION silver.num_chileno(t text) RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
    SELECT silver.num_plano(replace(replace(btrim(t), '.', ''), ',', '.'))
$$;

-- 'Sí' -> true, 'No' -> false, cualquier otra cosa -> NULL.
CREATE OR REPLACE FUNCTION silver.si_no(t text) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN lower(btrim(t)) IN ('sí', 'si') THEN true WHEN lower(btrim(t)) = 'no' THEN false END
$$;

-- Gastos comunes en CLP. Tres casos (el bug del proyecto de Concepción, ver docs/01):
--   con punto            -> miles reales ('82.000' = 82000)
--   sin punto, < 1.000   -> placeholder de "incluidos en el arriendo": 0
--   sin punto, >= 500.000 -> outlier implausible: NULL
CREATE OR REPLACE FUNCTION silver.gastos_comunes(t text) RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN t IS NULL OR btrim(t) = '' THEN NULL
        WHEN t LIKE '%.%' THEN silver.num_plano(replace(btrim(t), '.', ''))
        WHEN silver.num_plano(btrim(t)) < 1000 THEN 0
        WHEN silver.num_plano(btrim(t)) >= 500000 THEN NULL
        ELSE silver.num_plano(btrim(t))
    END
$$;

-- Distancias en metros de una lista de subtítulos del sitio ('8 mins - 620 metros', '12 mins - 1,2 km').
-- En kilómetros el separador es decimal; en metros el punto separa miles.
CREATE OR REPLACE FUNCTION silver.poi_distancias(arr jsonb) RETURNS numeric[] LANGUAGE sql IMMUTABLE AS $$
    SELECT array_agg(
        CASE WHEN lower(m[2]) = 'km'
             THEN silver.num_plano(replace(m[1], ',', '.')) * 1000
             ELSE silver.num_plano(replace(replace(m[1], '.', ''), ',', '.')) END)
    FROM jsonb_array_elements_text(arr) AS e(t),
         LATERAL regexp_match(e.t, '([\d.,]+)\s*(metros|km)', 'i') AS m
    WHERE m IS NOT NULL
$$;

-- Cuántos puntos de interés hay dentro del radio. NULL si Bronce no trae esa subcategoría (sin dato);
-- 0 si la trae y ninguno está cerca.
CREATE OR REPLACE FUNCTION silver.poi_cantidad(arr jsonb, radio numeric) RETURNS integer LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN arr IS NULL THEN NULL
                ELSE (SELECT count(*) FROM unnest(silver.poi_distancias(arr)) d WHERE d <= radio)::integer END
$$;

CREATE OR REPLACE FUNCTION silver.poi_distancia_min(arr jsonb, radio numeric) RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
    SELECT min(d) FROM unnest(silver.poi_distancias(arr)) d WHERE d <= radio
$$;

-- Fecha de publicación a partir del texto relativo del sitio, tomando como referencia el día en que se vio
-- (no el día de hoy). 'hoy' = 0 días; 'esta semana' = 3 días (punto medio del rango 1-6, aproximada);
-- 'hace N días|semanas|meses|años' con 30 días por mes y 365 por año.
CREATE OR REPLACE FUNCTION silver.fecha_publicacion(txt text, ref date) RETURNS date LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN txt IS NULL THEN NULL
        WHEN lower(btrim(txt)) = 'hoy' THEN ref
        WHEN lower(btrim(txt)) = 'esta semana' THEN ref - 3
        ELSE (SELECT CASE
                  WHEN x.u ~ '^d[ií]as?$'   THEN ref - x.n
                  WHEN x.u ~ '^semanas?$'   THEN ref - 7 * x.n
                  WHEN x.u ~ '^mes(es)?$'   THEN ref - 30 * x.n
                  WHEN x.u ~ '^a[ñn]os?$'   THEN ref - 365 * x.n
              END
              FROM (SELECT m[1]::int AS n, lower(m[2]) AS u
                    FROM regexp_match(txt, '(\d+)\s*(\S+)') AS m) x)
    END
$$;

CREATE OR REPLACE FUNCTION silver.fecha_publicacion_precision(txt text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN txt IS NULL THEN NULL
                WHEN lower(btrim(txt)) = 'esta semana' THEN 'aproximada_categoria'
                ELSE 'exacta' END
$$;

-- ---------------------------------------------------------------------------------------------------------
-- Indicadores diarios (UF y dólar), de mindicador.cl. Un valor por día; el dólar solo trae días hábiles,
-- así que las consultas usan el día anterior más cercano (con un máximo de días de antigüedad).
-- ---------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.indicadores_diarios (
    indicador   TEXT NOT NULL,                 -- 'uf' | 'dolar'
    fecha       DATE NOT NULL,
    valor       NUMERIC NOT NULL,
    cargado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (indicador, fecha)
);

-- ---------------------------------------------------------------------------------------------------------
-- Una fila por aviso, con su estado más reciente. Se reconstruye completa desde Bronce.
-- ---------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.avisos (
    id_aviso                    TEXT PRIMARY KEY,
    comuna                      TEXT NOT NULL,
    tipo_propiedad              TEXT,
    operacion                   TEXT,
    url                         TEXT,
    titulo                      TEXT,
    ubicacion                   TEXT,

    -- presencia en el sitio
    primera_vez_visto           TIMESTAMPTZ,
    ultima_vez_visto            TIMESTAMPTZ,
    fuera_de_grilla             BOOLEAN,        -- no apareció en la última corrida completa de su comuna
    fuera_de_alcance            BOOLEAN,        -- su comuna ya no se scrapea (no está en config.COMUNAS_RM): no se actualiza
    es_proyecto                BOOLEAN NOT NULL,
    tiene_detalle               BOOLEAN NOT NULL,
    ultima_visita_detalle       TIMESTAMPTZ,

    -- estado de publicación. NULL si todavía no se visitó el detalle; 'otro' si el texto no se reconoce.
    estado_texto                TEXT,
    estado_publicacion          TEXT,           -- activo | pausado | finalizado | otro

    -- precio en su moneda original y convertido
    precio_valor                NUMERIC,
    precio_moneda               TEXT,           -- CLP | CLF (UF) | USD
    precio_original             NUMERIC,        -- precio anterior si el aviso tiene rebaja
    tiene_rebaja                BOOLEAN,
    precio_grilla               NUMERIC,        -- precio de la tarjeta, por si no hay detalle
    moneda_grilla               TEXT,
    fecha_precio                DATE,           -- día de la última visita: fecha de conversión de monedas
    valor_uf                    NUMERIC,
    valor_dolar                 NUMERIC,
    precio_clp                  NUMERIC,        -- nominal, al valor del indicador en fecha_precio
    precio_original_clp         NUMERIC,
    gastos_comunes              NUMERIC,        -- CLP
    costo_total_clp             NUMERIC,        -- precio_clp + gastos_comunes (gastos NULL cuenta como 0)

    -- características
    dormitorios                 INTEGER,
    banos                       INTEGER,
    estacionamientos            INTEGER,
    bodegas                     INTEGER,
    tiene_bodega                BOOLEAN,
    superficie_total_m2         NUMERIC,
    superficie_util_m2          NUMERIC,
    superficie_grilla_m2        NUMERIC,
    antiguedad_anos             INTEGER,
    piso_unidad                 INTEGER,
    deptos_por_piso             INTEGER,
    max_habitantes              INTEGER,
    amoblado                    BOOLEAN,
    admite_mascotas             BOOLEAN,
    condominio_cerrado          BOOLEAN,
    estacionamiento_visitas     BOOLEAN,
    solo_familias               BOOLEAN,
    piscina                     BOOLEAN,
    quincho                     BOOLEAN,
    conserjeria                 BOOLEAN,
    ascensor                    BOOLEAN,

    -- ubicación
    latitud                     NUMERIC,
    longitud                    NUMERIC,
    barrio                      TEXT,
    descripcion                 TEXT,

    -- nivel socioeconómico del sector (IGVUST por Unidad Vecinal); NULL si el aviso no cae en ninguna UV
    uv_rsh                      BIGINT,
    rank_nac                    INTEGER,
    c_ig_com                    INTEGER,
    c_ig_reg                    INTEGER,
    c_ig_nac                    INTEGER,
    pob_rsh_uv                  NUMERIC,
    hog_uv                      NUMERIC,
    p_urbano                    NUMERIC,
    uv_sin_poligono             BOOLEAN,        -- tiene coordenadas pero ningún polígono las contiene

    -- fecha de publicación aproximada, calculada con el día en que se vio por primera vez
    fecha_publicacion_texto     TEXT,
    fecha_publicacion_aprox     DATE,
    fecha_publicacion_precision TEXT,

    -- puntos de interés a 500 m: cantidad y distancia mínima
    cantidad_paraderos                 INTEGER, distancia_min_m_paraderos                 NUMERIC,
    cantidad_estaciones_metro          INTEGER, distancia_min_m_estaciones_metro          NUMERIC,
    cantidad_jardines_infantiles       INTEGER, distancia_min_m_jardines_infantiles       NUMERIC,
    cantidad_colegios                  INTEGER, distancia_min_m_colegios                  NUMERIC,
    cantidad_universidades             INTEGER, distancia_min_m_universidades             NUMERIC,
    cantidad_plazas                    INTEGER, distancia_min_m_plazas                    NUMERIC,
    cantidad_supermercados             INTEGER, distancia_min_m_supermercados             NUMERIC,
    cantidad_farmacias                 INTEGER, distancia_min_m_farmacias                 NUMERIC,
    cantidad_centros_comerciales       INTEGER, distancia_min_m_centros_comerciales       NUMERIC,
    cantidad_hospitales                INTEGER, distancia_min_m_hospitales                NUMERIC,
    cantidad_clinicas                  INTEGER, distancia_min_m_clinicas                  NUMERIC,

    -- banderas de calidad (umbrales provisionales; ver 010_construir_avisos.sql)
    sin_coordenadas             BOOLEAN,
    coordenada_fuera_de_region  BOOLEAN,
    conteo_imposible            BOOLEAN,        -- dormitorios > 6, baños > 5 o estacionamientos > 15
    superficie_util_sospechosa  BOOLEAN,
    precio_sospechoso           BOOLEAN,
    precio_m2_atipico           BOOLEAN,        -- costo total por m2 útil muy lejos de lo normal en su comuna (z robusto > 5)
    gastos_comunes_faltante     BOOLEAN,
    moneda_sin_valor            BOOLEAN,        -- hay precio en UF o USD pero no se encontró el indicador

    construido_en               TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Si la tabla ya existía antes de agregar el nivel socioeconómico, CREATE TABLE IF NOT EXISTS no suma las
-- columnas nuevas; estas sentencias sí (idempotentes).
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS precio_m2_atipico BOOLEAN;
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS uv_rsh BIGINT;
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS rank_nac INTEGER;
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS c_ig_com INTEGER;
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS c_ig_reg INTEGER;
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS c_ig_nac INTEGER;
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS pob_rsh_uv NUMERIC;
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS hog_uv NUMERIC;
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS p_urbano NUMERIC;
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS uv_sin_poligono BOOLEAN;
ALTER TABLE silver.avisos ADD COLUMN IF NOT EXISTS fuera_de_alcance BOOLEAN;

-- Unidad Vecinal que contiene a cada aviso (cruce punto-en-polígono; lo calcula silver/asignar_uv.py).
CREATE TABLE IF NOT EXISTS silver.aviso_uv (
    id_aviso    TEXT PRIMARY KEY,
    uv_rsh      BIGINT NOT NULL
);
-- Es además un caché: guarda las coordenadas con que se asignó cada aviso y la "base" (carga del IGVUST y comunas usadas), para
-- no repetir el cruce punto-en-polígono con avisos que no cambiaron. Un aviso que no cae en ninguna UV queda con uv_rsh NULL.
ALTER TABLE silver.aviso_uv ALTER COLUMN uv_rsh DROP NOT NULL;
ALTER TABLE silver.aviso_uv ADD COLUMN IF NOT EXISTS latitud NUMERIC;
ALTER TABLE silver.aviso_uv ADD COLUMN IF NOT EXISTS longitud NUMERIC;
ALTER TABLE silver.aviso_uv ADD COLUMN IF NOT EXISTS base TEXT;

CREATE INDEX IF NOT EXISTS avisos_comuna_idx ON silver.avisos (comuna);
CREATE INDEX IF NOT EXISTS avisos_estado_idx ON silver.avisos (estado_publicacion);

-- ---------------------------------------------------------------------------------------------------------
-- Historia de observaciones del detalle: una fila por cada vez que Bronce registró un cambio en un aviso
-- (estado, precio u otro campo). Está tipada y con la moneda convertida a la fecha de cada observación, pero
-- SIN vigencias: construir los intervalos (valid_from, valid_to, is_current) de los SCD2 es trabajo de Gold,
-- que solo lee de Silver.
-- ---------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.aviso_observaciones (
    observacion_id      BIGINT PRIMARY KEY,      -- bronze.detalle_avisos.id
    id_aviso            TEXT NOT NULL,
    observado_en        TIMESTAMPTZ NOT NULL,
    fecha_observacion   DATE NOT NULL,           -- día (hora de Santiago) en que se vio: fecha de conversión
    motivo_visita       TEXT,                    -- nuevo | desaparecido | tarjeta_cambio | rotacion
    estado_texto        TEXT,
    estado_publicacion  TEXT NOT NULL,           -- activo | pausado | finalizado | otro
    precio_valor        NUMERIC,
    precio_moneda       TEXT,                    -- CLP | CLF (UF) | USD
    precio_original     NUMERIC,
    tiene_rebaja        BOOLEAN NOT NULL,
    valor_uf            NUMERIC,
    valor_dolar         NUMERIC,
    precio_clp          NUMERIC,
    precio_original_clp NUMERIC,
    gastos_comunes      NUMERIC,
    costo_total_clp     NUMERIC,
    moneda_sin_valor    BOOLEAN NOT NULL,
    construido_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS aviso_observaciones_id_idx ON silver.aviso_observaciones (id_aviso, observado_en);

-- Registro de cada construcción de Silver.
CREATE TABLE IF NOT EXISTS silver.construcciones (
    id              BIGSERIAL PRIMARY KEY,
    inicio          TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin             TIMESTAMPTZ,
    filas_avisos    INTEGER,
    detalle         TEXT
);
