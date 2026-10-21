-- Capa Gold: historial (SCD2) y dataset de entrenamiento. Gold SOLO lee de Silver (nunca de Bronce) y se
-- reconstruye completa en cada corrida. Idempotente: se re-aplica entero con gold/construir_gold.py.

CREATE SCHEMA IF NOT EXISTS gold;

-- ---------------------------------------------------------------------------------------------------------
-- SCD2 de estado de publicación. Un intervalo por cada estado consecutivo; valid_from es el instante en que
-- se OBSERVÓ por primera vez ese estado (no la hora de ejecución del pipeline), y valid_to es el valid_from
-- del estado siguiente. El intervalo vigente tiene valid_to NULL e is_current = true.
-- ---------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.dim_estado_aviso_scd2 (
    id_aviso            TEXT NOT NULL,
    valid_from          TIMESTAMPTZ NOT NULL,
    valid_to            TIMESTAMPTZ,
    is_current          BOOLEAN NOT NULL,
    estado_publicacion  TEXT NOT NULL,             -- activo | pausado | finalizado | otro
    estado_texto        TEXT,                      -- texto crudo del sitio ('Publicación finalizada')
    ultima_confirmacion TIMESTAMPTZ,               -- solo en el intervalo vigente: última visita exitosa
    PRIMARY KEY (id_aviso, valid_from)
);

-- ---------------------------------------------------------------------------------------------------------
-- SCD2 de precio, en la MONEDA ORIGINAL del aviso. Un aviso a 18 UF no cambia de precio cuando la UF sube:
-- versionar el CLP generaría una "rebaja" falsa cada día. precio_clp_observado es el equivalente en pesos
-- al inicio del intervalo, solo informativo.
-- ---------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.dim_precio_aviso_scd2 (
    id_aviso            TEXT NOT NULL,
    valid_from          TIMESTAMPTZ NOT NULL,
    valid_to            TIMESTAMPTZ,
    is_current          BOOLEAN NOT NULL,
    precio_valor        NUMERIC,
    precio_moneda       TEXT,
    precio_original     NUMERIC,                   -- precio anterior si el aviso tiene rebaja
    tiene_rebaja        BOOLEAN NOT NULL,
    precio_clp_observado NUMERIC,
    ultima_confirmacion TIMESTAMPTZ,
    PRIMARY KEY (id_aviso, valid_from)
);

-- ---------------------------------------------------------------------------------------------------------
-- Dataset de entrenamiento: una fila por aviso. Incluye TODOS los avisos; los que no sirven para entrenar
-- quedan con apto_entrenamiento = false y su motivo, para poder revisarlos y cambiar la regla sin perderlos.
-- No contiene features que dependan del split de entrenamiento (nivel_barrio, precio_m2_sector, imputación
-- de superficie): esas se calculan en el código del modelo ajustándolas solo con train, para no repetir la
-- fuga de datos que tenía el proyecto de Concepción.
-- ---------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.aviso_entrenamiento (
    id_aviso                    TEXT PRIMARY KEY,
    comuna                      TEXT NOT NULL,
    barrio                      TEXT,

    apto_entrenamiento          BOOLEAN NOT NULL,
    motivo_exclusion            TEXT,               -- motivos separados por coma; NULL si es apto

    -- ciclo de vida
    estado_publicacion          TEXT,
    fecha_publicacion_aprox     DATE,
    fecha_publicacion_precision TEXT,
    primera_vez_visto           TIMESTAMPTZ,
    ultima_vez_visto            TIMESTAMPTZ,
    dias_en_mercado             INTEGER,            -- desde la publicación hasta la última vez visto
    n_cambios_estado            INTEGER,
    n_cambios_precio            INTEGER,

    -- target: costo mensual total, en pesos nominales y en UF (se elige al entrenar)
    precio_valor                NUMERIC,
    precio_moneda               TEXT,
    tiene_rebaja                BOOLEAN,
    fecha_precio                DATE,
    precio_clp                  NUMERIC,
    gastos_comunes              NUMERIC,
    costo_total_clp             NUMERIC,
    costo_total_uf              NUMERIC,
    gastos_comunes_faltante     BOOLEAN,

    -- características de la propiedad
    dormitorios                 INTEGER,
    banos                       INTEGER,
    estacionamientos            INTEGER,
    bodegas                     INTEGER,
    tiene_bodega                BOOLEAN,
    superficie_total_m2         NUMERIC,
    superficie_util_m2          NUMERIC,
    antiguedad_anos             INTEGER,
    antiguedad_origen           TEXT,               -- aviso | mismo_punto | vecinos | sin_dato
    piso_unidad                 INTEGER,
    deptos_por_piso             INTEGER,
    amoblado                    BOOLEAN,
    admite_mascotas             BOOLEAN,
    condominio_cerrado          BOOLEAN,
    estacionamiento_visitas     BOOLEAN,
    piscina                     BOOLEAN,
    quincho                     BOOLEAN,
    conserjeria                 BOOLEAN,
    ascensor                    BOOLEAN,

    -- ubicación y entorno
    latitud                     NUMERIC,
    longitud                    NUMERIC,
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

    -- nivel socioeconómico del sector (IGVUST)
    uv_rsh                      BIGINT,
    rank_nac                    INTEGER,
    c_ig_com                    INTEGER,
    c_ig_reg                    INTEGER,
    c_ig_nac                    INTEGER,
    pob_rsh_uv                  NUMERIC,
    hog_uv                      NUMERIC,
    p_urbano                    NUMERIC,

    -- texto del aviso: lo usa el modelo (palabras clave y un modelo de texto); no es una variable por sí mismo
    titulo                      TEXT,
    descripcion                 TEXT,
    url                         TEXT,               -- enlace a la publicación (lo usa el mapa)

    construido_en               TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Si la tabla ya existía, CREATE TABLE IF NOT EXISTS no suma las columnas nuevas; estas sentencias sí.
ALTER TABLE gold.aviso_entrenamiento ADD COLUMN IF NOT EXISTS titulo TEXT;
ALTER TABLE gold.aviso_entrenamiento ADD COLUMN IF NOT EXISTS descripcion TEXT;
ALTER TABLE gold.aviso_entrenamiento ADD COLUMN IF NOT EXISTS url TEXT;
ALTER TABLE gold.aviso_entrenamiento ADD COLUMN IF NOT EXISTS antiguedad_origen TEXT;
CREATE INDEX IF NOT EXISTS aviso_entrenamiento_apto_idx ON gold.aviso_entrenamiento (apto_entrenamiento);
CREATE INDEX IF NOT EXISTS aviso_entrenamiento_comuna_idx ON gold.aviso_entrenamiento (comuna);

CREATE TABLE IF NOT EXISTS gold.construcciones (
    id              BIGSERIAL PRIMARY KEY,
    inicio          TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin             TIMESTAMPTZ,
    detalle         TEXT
);

-- ---------------------------------------------------------------------------------------------------------
-- Predicciones del modelo. A diferencia del resto de Gold NO se reconstruye: las corridas de construir_gold
-- no la vacían (010 y 020 no la tocan). Solo se agregan filas, una por aviso y por corrida de scoring, con la
-- versión del modelo que predijo; así queda el historial para medir la degradación contra precios reales.
-- Solo la escribe el rol ml_scoring (INSERT).
-- ---------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.predicciones (
    id_prediccion               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_aviso                    TEXT NOT NULL,
    predicho_en                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    modelo_nombre               TEXT NOT NULL,
    modelo_version              INTEGER NOT NULL,
    huella_datos                TEXT,
    costo_total_predicho_clp    NUMERIC NOT NULL
);
CREATE INDEX IF NOT EXISTS predicciones_aviso_idx ON gold.predicciones (id_aviso, predicho_en);

-- Etiquetado de mercado (oportunidad / precio de mercado / caro) y confianza de la estimación. Se agregan después de crear
-- la tabla, con ALTER, para no perder las predicciones ya guardadas: las filas anteriores quedan con estos campos en NULL.
ALTER TABLE gold.predicciones ADD COLUMN IF NOT EXISTS costo_total_publicado_clp NUMERIC;  -- lo que cuesta el aviso (arriendo + gastos comunes)
ALTER TABLE gold.predicciones ADD COLUMN IF NOT EXISTS cv_ensamble NUMERIC;                -- desviación / media de las 10 predicciones del ensamble
ALTER TABLE gold.predicciones ADD COLUMN IF NOT EXISTS nivel_confianza TEXT;              -- alta confianza | confianza media | baja confianza
ALTER TABLE gold.predicciones ADD COLUMN IF NOT EXISTS z_robusto NUMERIC;                  -- error normalizado por decil de costo (mediana / MAD)
ALTER TABLE gold.predicciones ADD COLUMN IF NOT EXISTS etiqueta TEXT;                     -- oportunidad | precio_de_mercado | caro
ALTER TABLE gold.predicciones ADD COLUMN IF NOT EXISTS banda_inferior_clp NUMERIC;        -- rango de costo total que sería precio de mercado
ALTER TABLE gold.predicciones ADD COLUMN IF NOT EXISTS banda_superior_clp NUMERIC;

-- La predicción vigente de cada aviso: la de la versión más nueva del modelo y, dentro de ella, la más reciente.
CREATE OR REPLACE VIEW gold.predicciones_vigentes AS
    SELECT DISTINCT ON (id_aviso) *
    FROM gold.predicciones
    ORDER BY id_aviso, modelo_version DESC, predicho_en DESC;

-- Cifras del modelo @champion que explica el mapa (pestaña "Cómo funciona"). La escribe el scoring (rol ml_scoring) cuando
-- ve una versión nueva del champion; la lee el mapa. Una fila por versión; sin dato personal ni de avisos.
CREATE TABLE IF NOT EXISTS gold.modelo_vigente (
    modelo_nombre   TEXT NOT NULL,
    modelo_version  INTEGER NOT NULL,
    publicado_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
    cifras          JSONB NOT NULL,
    PRIMARY KEY (modelo_nombre, modelo_version)
);
-- Permisos para los roles de lectura y de scoring, si existen (en otro entorno pueden no estar creados).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ml_scoring') THEN
        GRANT SELECT, INSERT, UPDATE ON gold.modelo_vigente TO ml_scoring;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vis_lectura') THEN
        GRANT SELECT ON gold.modelo_vigente TO vis_lectura;
    END IF;
END $$;
