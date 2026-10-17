-- Capa Bronze: datos tal como vienen del sitio. Sin limpieza, sin conversión de monedas, sin deduplicar
-- entre corridas más allá del hash. Todo cambio de schema va en un archivo nuevo (002_..., 003_...):
-- este archivo es idempotente y se re-aplica completo con scripts/aplicar_ddl.py.

CREATE SCHEMA IF NOT EXISTS bronze;

-- Una fila por ejecución del scraper.
CREATE TABLE IF NOT EXISTS bronze.runs (
    run_id          BIGSERIAL PRIMARY KEY,
    fuente          TEXT NOT NULL,                 -- 'grilla' | 'detalle'
    inicio          TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin             TIMESTAMPTZ,
    estado          TEXT NOT NULL DEFAULT 'en_curso',  -- en_curso | success | parcial | bloqueado | error
    paginas         INTEGER NOT NULL DEFAULT 0,
    filas_nuevas    INTEGER NOT NULL DEFAULT 0,
    detalle         TEXT
);

-- Una fila por página pedida al sitio: es el log de auditoría y el detector de "páginas vacías anómalas".
-- html_path apunta al HTML crudo en el landing local (permite reparsear sin volver a pedir).
CREATE TABLE IF NOT EXISTS bronze.grilla_paginas (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES bronze.runs(run_id),
    comuna          TEXT NOT NULL,
    tipo_propiedad  TEXT NOT NULL,
    pagina          INTEGER NOT NULL,
    url             TEXT NOT NULL,
    http_status     INTEGER,
    n_tarjetas      INTEGER,
    total_declarado INTEGER,                       -- "N resultados" que muestra el sitio (solo página 1)
    html_path       TEXT,
    html_sha256     TEXT,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS grilla_paginas_run_idx ON bronze.grilla_paginas (run_id);

-- Observaciones de la grilla, append-only: solo se inserta una fila cuando el payload cambió respecto de la
-- última observación del mismo aviso (hash_payload). Así queda el historial de precios sin repetir lo igual.
CREATE TABLE IF NOT EXISTS bronze.grilla_avisos (
    id              BIGSERIAL PRIMARY KEY,
    id_aviso        TEXT NOT NULL,
    comuna          TEXT NOT NULL,
    tipo_propiedad  TEXT NOT NULL,
    operacion       TEXT NOT NULL,
    run_id          BIGINT NOT NULL REFERENCES bronze.runs(run_id),
    pagina          INTEGER NOT NULL,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    hash_payload    TEXT NOT NULL,
    payload         JSONB NOT NULL                 -- strings crudos de la tarjeta
);
CREATE INDEX IF NOT EXISTS grilla_avisos_id_idx ON bronze.grilla_avisos (id_aviso, scraped_at DESC);

-- Primera y última vez que un aviso apareció en la grilla. Como grilla_avisos omite lo que no cambió,
-- esta tabla es la que permite a Silver detectar avisos que dejaron de aparecer.
CREATE TABLE IF NOT EXISTS bronze.grilla_vistos (
    id_aviso        TEXT PRIMARY KEY,
    primera_vez     TIMESTAMPTZ NOT NULL,
    ultima_vez      TIMESTAMPTZ NOT NULL,
    ultimo_run_id   BIGINT NOT NULL REFERENCES bronze.runs(run_id)
);
-- El detalle de cada aviso vive en 002_detalle.sql.
