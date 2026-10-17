-- Cobertura de la grilla por comuna. El sitio corta cada búsqueda en 2.016 resultados (42 páginas x 48), así
-- que una comuna grande se parte en rangos de precio; acá se registra si al final se capturó lo que el sitio
-- declara. Es lo que permite saber qué corrida "vio completa" una comuna (los avisos que no aparecieron en
-- ella son candidatos a desaparecidos) sin que una corrida parcial contamine a las demás comunas.

ALTER TABLE bronze.grilla_paginas ADD COLUMN IF NOT EXISTS segmento TEXT;  -- rango de precio 'min-max' en CLP; NULL = sin filtro

CREATE TABLE IF NOT EXISTS bronze.grilla_cobertura (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES bronze.runs(run_id),
    comuna          TEXT NOT NULL,
    tipo_propiedad  TEXT NOT NULL,
    segmentada      BOOLEAN NOT NULL,
    total_declarado INTEGER,                      -- "N resultados" de la búsqueda sin filtro
    avisos_unicos   INTEGER NOT NULL,             -- IDs distintos vistos en esta corrida para la comuna
    estado          TEXT NOT NULL,                -- completa | parcial
    registrado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS grilla_cobertura_comuna_idx ON bronze.grilla_cobertura (comuna, run_id DESC);

-- Primera carga completa (la corrida de >200 páginas): se reconstruye su cobertura una sola vez desde lo ya
-- guardado. En esa corrida todo se insertó (la base solo tenía pruebas chicas), así que contar filas = contar avisos.
INSERT INTO bronze.grilla_cobertura (run_id, comuna, tipo_propiedad, segmentada, total_declarado, avisos_unicos, estado)
SELECT g.run_id, g.comuna, g.tipo_propiedad, FALSE, p.total_declarado, count(DISTINCT g.id_aviso),
       CASE WHEN count(DISTINCT g.id_aviso) >= p.total_declarado - GREATEST(10, p.total_declarado / 100)
            THEN 'completa' ELSE 'parcial' END
FROM bronze.grilla_avisos g
JOIN bronze.grilla_paginas p
  ON p.run_id = g.run_id AND p.comuna = g.comuna AND p.tipo_propiedad = g.tipo_propiedad AND p.pagina = 1
WHERE g.run_id = (SELECT min(run_id) FROM bronze.runs WHERE fuente = 'grilla' AND paginas > 200)
  AND NOT EXISTS (SELECT 1 FROM bronze.grilla_cobertura c WHERE c.run_id = g.run_id AND c.comuna = g.comuna)
GROUP BY g.run_id, g.comuna, g.tipo_propiedad, p.total_declarado;

-- Las comunas que ya estaban cargadas por pruebas previas no insertaron filas en esa corrida (el hash no
-- cambió), así que no aparecen arriba. Se cuentan sus avisos únicos de todas las corridas.
INSERT INTO bronze.grilla_cobertura (run_id, comuna, tipo_propiedad, segmentada, total_declarado, avisos_unicos, estado)
SELECT p.run_id, p.comuna, p.tipo_propiedad, FALSE, p.total_declarado, u.n,
       CASE WHEN u.n >= p.total_declarado - GREATEST(10, p.total_declarado / 100) THEN 'completa' ELSE 'parcial' END
FROM bronze.grilla_paginas p
JOIN (SELECT comuna, count(DISTINCT id_aviso) AS n FROM bronze.grilla_avisos GROUP BY comuna) u USING (comuna)
WHERE p.pagina = 1
  AND p.run_id = (SELECT min(run_id) FROM bronze.runs WHERE fuente = 'grilla' AND paginas > 200)
  AND NOT EXISTS (SELECT 1 FROM bronze.grilla_cobertura c WHERE c.run_id = p.run_id AND c.comuna = p.comuna);
