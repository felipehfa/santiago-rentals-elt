-- Copia a silver.avisos el nivel socioeconómico de la Unidad Vecinal de cada aviso. Corre después de
-- silver/asignar_uv.py, que llena silver.aviso_uv. Silver no imputa: un aviso que no cae en ninguna UV queda
-- con NULL y la bandera uv_sin_poligono; es Gold (o el código de entrenamiento) quien decide cómo rellenarlo.

UPDATE silver.avisos a
SET uv_rsh     = u.uv_rsh,
    rank_nac   = v.rank_nac,
    c_ig_com   = v.c_ig_com,
    c_ig_reg   = v.c_ig_reg,
    c_ig_nac   = v.c_ig_nac,
    pob_rsh_uv = v.pob_rsh_uv,
    hog_uv     = v.hog_uv,
    p_urbano   = v.p_urbano
FROM silver.aviso_uv u
JOIN bronze.igvust_uv v ON v.uv_rsh = u.uv_rsh
WHERE a.id_aviso = u.id_aviso;

UPDATE silver.avisos
SET uv_sin_poligono = (latitud IS NOT NULL AND longitud IS NOT NULL AND uv_rsh IS NULL);
