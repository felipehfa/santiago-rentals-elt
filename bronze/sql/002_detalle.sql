-- Detalle de cada aviso. Dos tablas con roles distintos, ambas append-only (ningún UPDATE):
--   detalle_intentos: UNA fila por cada visita a una página de aviso, con su resultado. Es el log de
--                     auditoría y de él se deriva la cola de pendientes (sin contadores mutables).
--   detalle_avisos:   una fila solo cuando la visita fue exitosa Y lo observado cambió respecto de la
--                     última observación (hash). De acá sale la historia que Silver tipa y de la que Gold deriva las SCD2 de estado y precio.

CREATE TABLE IF NOT EXISTS bronze.detalle_intentos (
    id              BIGSERIAL PRIMARY KEY,
    id_aviso        TEXT NOT NULL,
    run_id          BIGINT NOT NULL REFERENCES bronze.runs(run_id),
    motivo_visita   TEXT NOT NULL,   -- nuevo | desaparecido | tarjeta_cambio | rotacion
    resultado       TEXT NOT NULL,   -- ok | error | no_encontrado | captcha | bloqueado | proyecto
                                     -- proyecto = la URL lleva a un proyecto inmobiliario, no a un aviso
    detalle         TEXT,            -- causa del fallo, si la hubo
    http_status     INTEGER,
    url_final       TEXT,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS detalle_intentos_id_idx ON bronze.detalle_intentos (id_aviso, scraped_at DESC);

CREATE TABLE IF NOT EXISTS bronze.detalle_avisos (
    id              BIGSERIAL PRIMARY KEY,
    id_aviso        TEXT NOT NULL,
    run_id          BIGINT NOT NULL REFERENCES bronze.runs(run_id),
    motivo_visita   TEXT NOT NULL,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Evidencia cruda de estado y precio. Bronce no interpreta: activo / pausado / finalizado se deriva
    -- en Silver. estado_texto es NULL cuando la página no trae banner de estado (aviso activo).
    estado_texto    TEXT,
    precio_valor    NUMERIC,
    precio_moneda   TEXT,            -- CLP | CLF (UF) | USD
    precio_original NUMERIC,         -- solo viene si el aviso tiene rebaja
    canonical       TEXT,
    og_url          TEXT,
    html_path       TEXT,            -- HTML crudo local, solo cuando entra una fila nueva
    hash_payload    TEXT NOT NULL,
    payload         JSONB NOT NULL   -- resto de campos extraídos, como strings crudos
);
CREATE INDEX IF NOT EXISTS detalle_avisos_id_idx ON bronze.detalle_avisos (id_aviso, scraped_at DESC);
