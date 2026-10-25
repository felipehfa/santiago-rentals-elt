# Antecedentes: proyecto de Concepción y proyecto de Databricks

Qué se construyó antes, por qué se decidió así, qué falló y cómo se resolvió. Sirve de base para
`santiago-rentals`. Las fuentes son el `README.md`, el `CLAUDE.md` y el historial de git de
`gran-concepcion-rentals`, y el `README.md`, el `CLAUDE.md` y el historial de git de `databricks`.
Las cifras citadas vienen de esos documentos y no se volvieron a medir.

Contenido: las secciones 1 y 2 describen cada proyecto y sus problemas; la 3 resume las lecciones; las
secciones 4 y 5 son la **referencia técnica para Silver y Gold** (reglas de limpieza, umbrales,
imputaciones, features y modelo); la 6 lista lo que probablemente no se traspasa a la Región
Metropolitana; la 7 los cuidados para las etapas siguientes; y la 8 la tabla de qué se hereda y qué
cambia en `santiago-rentals`.

---

## 1. Proyecto de Concepción (`gran-concepcion-rentals`)

### 1.1 Qué es

Pipeline de scraping, modelo de ML y dashboard que estima si el arriendo de un departamento del Gran
Concepción está caro, barato o a precio de mercado. Tres partes:

| Parte | Rol |
|---|---|
| `modelamiento/` | Ingeniería de variables y entrenamiento. Lee de Supabase. |
| `produccion/01_modelo_produccion/` | Pipeline orquestado: grilla, detalle, vulnerabilidad, variables, predicción, historial diario. Corría cada 4 h en GitHub Actions. |
| `produccion/03_visualizacion/` | Dashboard Streamlit de solo lectura. |

Es un proyecto operativo: el pipeline, la base y el dashboard corrían solos.

### 1.2 Arquitectura de datos

- **Base:** Supabase (Postgres). Nueve tablas: `avisos`, `avisos_detalle`, `poligonos_vulnerabilidad_uv`,
  `predicciones`, `corridas`, `logs_ejecucion`, `historial_diario_avisos`, `control`, `valores_uf`.
  El schema se crea con `CREATE TABLE IF NOT EXISTS` en `db.py`. No hay migraciones versionadas: un
  `ALTER TABLE` sobre una tabla existente se hace con SQL manual.
- **Un solo nivel:** no hay capas medallón. `avisos` y `avisos_detalle` mezclan datos crudos, estado
  de publicación mutable y contadores de reintentos.
- **Dos roles de Postgres, mínimo privilegio:** `postgres` (orquestador, dueño del schema) y
  `streamlit_app` (`SELECT` en todo `public`, `INSERT`/`UPDATE` solo en `valores_uf`, sin `CREATE`).
- **Conexión:** `BD_STRING` por entorno (`.env`, secret de GitHub Actions, secret de Streamlit).
  Pooler de Supabase en modo transaction, puerto 6543.
- **Scrapers:** viven en `scrapers_base/` y el pipeline los importa con `importlib`, para no duplicar
  el parseo. Dos scrapers: grilla (`requests` + BeautifulSoup) y detalle (`requests`; Playwright como
  respaldo).

### 1.3 Decisiones de scraping

| Decisión | Motivo |
|---|---|
| Playwright → `requests` | Se comprobó equivalencia con 6 URLs comparadas 1 a 1 y 150 requests sin bloqueo: el HTML ya trae server-side el mismo JSON que renderizaba Playwright. Playwright quedó como respaldo (`--fallback-playwright`). |
| Guardado incremental y reanudable | Commit por página o aviso, `INSERT OR IGNORE` por `id_aviso`. Una corrida cortada se retoma sin perder nada. |
| Corte temprano por duplicados | Si una página completa ya existía, se corta esa búsqueda. |
| POIs desde el JSON embebido `window._n.ctx.r` | Trae todas las categorías aunque la pestaña no esté abierta. "Cercano" = dentro de 500 m. |
| Detección de CAPTCHA con doble condición | La palabra "captcha" **y** que el contenido normal no haya cargado, porque el reCAPTCHA de fondo casi siempre está presente. |
| Producción no scrapea casas | El resto del pipeline las descartaba, así que se ahorró presupuesto de requests. |
| Estado de publicación por re-chequeo | Avisos `activo` y `pausado` vencidos (más de 1 día) se vuelven a visitar. Pausado se incluye para detectar si vuelve a publicarse. |

### 1.4 Decisiones de modelamiento

- **Target:** `costo_total_clp = precio_clp + gastos_comunes`, no solo el arriendo, porque los gastos
  comunes cambian qué tan buen negocio es un arriendo. `gastos_comunes` y `precio_clp` dejaron de ser
  features porque serían fuga casi perfecta.
- **29 features finales**, elegidas por estabilidad: SHAP + 30 modelos + K-Fold + regla de 1 error
  estándar. Reparto de importancia: variables físicas ~75 %, ubicación y mercado local ~16 %, contexto
  socioeconómico ~9 %.
- **Algoritmo:** se comparan XGBoost y LightGBM sobre las mismas features y gana LightGBM por criterio
  ponderado (50 % MAE + 50 % RMSE). Random Forest se probó y quedó por debajo.
- **Rigor del split:** estratificado por quintil de precio (el split aleatorio era inestable entre
  corridas); objective fijado a mano, no como hiperparámetro de Optuna (el "ganador" cambiaba por ruido
  de los folds); validación multi-semilla disponible aparte por su costo.
- **Descartado dos veces:** `log(precio)` como target (empeoró todas las métricas) y separar un modelo
  "premium" (el problema del quintil caro es volumen de datos, no una estructura de precios distinta).
- **Etiquetado "oportunidad / caro":** deciles de precio, mediana y MAD del error por decil
  (`z_robusto`), y confianza por terciles del CV del ensamble. Se persisten en
  `parametros_produccion.json` para etiquetar avisos nuevos sin recalcular una distribución con una fila.
- **Versionado de modelos:** `v{contador}_{timestamp}_{algoritmo}_{hash}`, archivado sin sobrescribir.
- **Resultados citados:** v0006 MAE 61.470 / R² 0,80; v0007 MAE 42.532 / R² 0,876.

### 1.5 Problemas resueltos

**Datos y modelo**

| Problema | Causa | Resolución |
|---|---|---|
| Fuga de datos en `precio_m2` (MAPE artificial de ~3,6 %) | El precio/m² de sector se calculaba con el precio de la propia fila | Se calcula solo con comparables de otras propiedades en 300 m, con filtro IQR ×3, mediana y fallback marcado en `tiene_comparables_cercanos` |
| `gastos_comunes` perdía el separador de miles (afectó 1.411 de 1.956 avisos, 72 %) | `float("82.000")` daba 82,0 | Tres casos: con punto se limpia; dígito suelto menor a 1.000 es placeholder de "incluido" y pasa a 0; sin punto y 500.000 o más es outlier y pasa a NULL. Respaldo con la insignia de resumen recuperó 102 de 190 NULL. Mejoró las cinco métricas |
| `avisos_detalle.banos` capturaba la superficie (851 de 1.782, 48 %) | Regex con `IGNORECASE` encontraba antes la insignia "2 baños 75 m² totales" que la sección de características | Regex sin `IGNORECASE`, con backfill. Ningún modelo se afectó porque usaba `avisos.banos` |
| `condominio_cerrado` perdía el 78 % de sus datos contra Postgres | `.str.lower()` devuelve NaN sobre una columna INTEGER | Conversión corregida |
| Un aviso con coordenadas en Madrid generó una distancia fuera de rango como feature | Sin validación geográfica | Corregido; en Databricks se añadió una caja de sanidad del Gran Concepción |
| Precio y moneda mezclados en la grilla | Selectores independientes tomaban el precio "Antes" tachado con la moneda del "Ahora" | Ambos se extraen del mismo widget de precio vigente |
| Sesgo de supervivencia en el entrenamiento | Un aviso que sigue activo es uno que el mercado no absorbió: sobrerrepresenta unidades caras | Entrenar con activos, pausados y finalizados recientes (~2.430 filas contra 1.414 solo activos). El límite de antigüedad usa `fecha_publicacion_aprox`, no `fecha_ultimo_chequeo_estado` |

**Pipeline y operación**

| Problema | Causa | Resolución |
|---|---|---|
| El `.db` SQLite versionado crecía sin techo y el dashboard leía archivos a medio escribir | Se commiteaba un binario reescrito en cada corrida (6 por día) | Migración a Supabase (26-jul-2026) |
| Un merge automático pisó la base y se perdieron cambios | `.gitattributes` con `merge=keep-incoming` resolvía conflictos sin avisar | Se cambió a `-merge`; se recuperó la base comparando campo a campo (4.618 filas de historial, 9 fechas de UF, superficie de 314 avisos) |
| `InsufficientPrivilege` en el dashboard | `valores_uf` se creaba desde un código que corría con el rol sin `CREATE` | La tabla se crea con el rol dueño; documentado en SETUP |
| El scraper visitaba dos veces el mismo aviso nuevo (como "nuevo" y como "re-chequeo") | Las dos colas se solapaban | Se filtran los ya existentes en `avisos_detalle` |
| Nada leía el `.env` local | Faltaba cargarlo | Corregido |
| Dashboard: filtros que ocultaban avisos | Dormitorios 0 fuera de los buckets; sliders truncados con `int()`; "confianza baja" invertido contra el valor real | Bucket "Sin especificar", `floor`/`ceil`, valor corregido |
| CARTO estampó "API KEY REQUIRED" en el mapa | Dejó de servir tiles sin API key | Migración a tiles de Esri (ojo: orden `{z}/{y}/{x}`) |

**Incidente 1: muro de verificación (agosto 2026).** Entre el 5 y el 9 de agosto el sitio redirigió el
tráfico automatizado, incluso la portada, a `/gz/account-verification` con HTTP 200 y sin CAPTCHA
visible. El chequeo de canonical/og:url falló para todos los avisos y el scraper lo tomó como "aviso
eliminado": **1.543 avisos activos quedaron como `no_disponible`** y el dashboard se vació. Se
diagnosticó cruzando el salto de estado concentrado en tres días con `intentos_fallidos_detalle = 0` en
el 100 % de las filas (ninguna pasó por reintentos). Resolución:

- Nuevo resultado `bloqueado`, detectado por la URL final, que corta la corrida sin tocar ningún estado.
- `no_encontrado` ya no marca `no_disponible` de inmediato: pasa por el contador de fallos.
- Se revirtieron los 1.543 avisos y se pausó y reactivó el cron.

**Incidente 2: bloqueo silencioso a IPs de datacenter (octubre 2026).** Desde el 30 de septiembre, el
sitio devolvió HTML válido pero sin tarjetas de resultado a las IPs de GitHub Actions. El pipeline lo
leyó como "no hay más resultados" y cada corrida terminó en `success`: **17 días sin que nada fallara**.
Desde una IP residencial, el mismo código trajo 48 avisos por página. Se pausó el cron, se borraron las
44 corridas del período roto y sus 15.461 registros de log, y se reinició el contador de fallos de 54
avisos. **Lección: una respuesta vacía no es un éxito.** Es la razón por la que `santiago-rentals`
corre local y tiene un detector de página 1 vacía.

### 1.6 Limitaciones conocidas del proyecto

Dataset chico y transversal; el quintil más caro tiene menos datos; no hay variables de calidad, vista
o estado de conservación; las coordenadas son aproximadas al sector; el target hereda los errores de
`gastos_comunes`; dependencia de la estructura HTML del sitio.

---

## 2. Proyecto de Databricks (`databricks`)

### 2.1 Qué es

Réplica del pipeline de Concepción sobre Databricks (Unity Catalog, Delta Lake), en arquitectura
medallón de tres capas: catálogo `gran_concepcion`, esquemas `01_bronce`, `02_plata`, `03_oro`. Era el
proyecto **operativo**: orquestaba notebooks, predecía y alimentaba un dashboard (Power BI y un
dashboard `.lvdash`). Los modelos **no** se entrenan ahí: se entrenan en el proyecto de Concepción y se
suben como `.pkl` a un Volume.

### 2.2 Cómo aplica el estándar medallón

| Principio | Implementación |
|---|---|
| **Bronce append-only** | Solo `INSERT`. El control de reintentos del scraper vive en un log, `intentos_scraping_detalle` (una fila por intento: `ok`, `error`, `no_encontrado`), y la cola de pendientes se deriva con una consulta (conteo de errores, `NOT EXISTS` de no encontrados), no con un contador mutable. |
| **Bronce sin tipar** | Todas las columnas son `STRING`. El tipado ocurre en Plata. |
| **Gold lee solo de Silver** | Excepción documentada: los polígonos de vulnerabilidad, que son referencia estática. Una columna nueva de Bronce que Oro necesite se agrega a la selección de Plata (así viaja `url`). |
| **Metadata por fila** | `_sistema_origen` y `_id_corrida` (uuid por ejecución), con prefijo `_` para separarlas de las columnas de negocio. |
| **Incrementalidad** | `NOT EXISTS` contra la tabla destino o `CREATE TABLE AS SELECT` si no existe. `ROW_NUMBER() OVER (PARTITION BY id_aviso ...)` como red de seguridad ante corridas solapadas. Nunca `INSERT OVERWRITE` sin filtro. |
| **Particionado y compactación** | `PARTITIONED BY` fecha en las tablas que crecen y `OPTIMIZE ... ZORDER BY (id_aviso)` al final de cada notebook. Sin `VACUUM` automático. |
| **Una sola capa Gold** | La predicción vive dentro de Oro, no en un cuarto esquema. |

### 2.3 Capa Oro

- **Población de referencia congelada:** las features de un aviso nuevo se calculan contra el dataset
  con el que se entrenó el modelo, nunca contra los avisos que van llegando. Así un aviso nuevo recibe
  las mismas features que habría recibido en el entrenamiento.
- **Cascada de valores faltantes:** valor real del aviso, luego vecinos de la referencia (Haversine, radio
  por feature), luego mediana por comuna, luego mediana global.
- **Vulnerabilidad en dos pasos:** SQL deja un respaldo por comuna y Python con `shapely` resuelve el
  punto-en-polígono real y sobrescribe con `MERGE` solo donde encontró polígono. Sin `geopandas`/GDAL
  para no cargar dependencias pesadas en el cluster.
- **Estado de publicación:** Bronce guarda el estado de la **primera** visita; un notebook de Oro
  re-chequea los activos y mantiene el estado actual. Es la fuente de verdad del estado.
- **Modelo dimensional (Kimball) para Power BI:** `dim_barrio`, `dim_descripcion_propiedad`,
  `dim_amenidades`, `dim_ubicacion`, `dim_tiempo`, `dim_estado_aviso_scd2`, `dim_prediccion_scd2` y
  `fact_aviso`, más vistas para el buscador.

### 2.4 SCD2 tal como quedó implementado

Dos dimensiones, `dim_estado_aviso_scd2` y `dim_prediccion_scd2`.

```
clave sustituta (IDENTITY) | id_aviso | atributo(s) versionado(s) | valid_from | valid_to | is_current
```

Patrón **cerrar antes de insertar**, en este orden:

1. `UPDATE` que cierra (`valid_to = now()`, `is_current = false`) la fila vigente si el valor del
   staging difiere del actual.
2. `INSERT` de la fila nueva para los avisos que quedaron sin fila vigente.

Si se insertara primero, el cierre alcanzaría a la fila recién insertada.

Limitaciones que **no** conviene copiar:

- `valid_from` es la hora en que corrió el pipeline, no cuándo cambió el aviso.
- Compara con `<>`, que se salta los NULL (en Postgres corresponde `IS DISTINCT FROM`).
- Su `CLAUDE.md` documenta una `dim_precio_scd2` (precio crudo en moneda original, nunca el CLP) que
  **no existe en el repositorio**. El criterio es útil; el código no existe.

### 2.5 Problemas resueltos

| Problema | Causa | Resolución |
|---|---|---|
| `CAST_INVALID_INPUT` en `cantidad_*` | Bronce entrega `"N.0"` como STRING y el modo ANSI no tolera `CAST` directo a INT | Todo el tipado de crudos se movió a Plata |
| `CREATE OR REPLACE TABLE` dejaba la tabla sin partición | `PARTITIONED BY` solo aplica al crear y el `REPLACE` no lo conserva | Repetirlo explícitamente en cada `CREATE OR REPLACE` |
| `ZORDER` falló en predicciones | No puede apuntar a la columna de partición | Se cambió la columna |
| `hog_uv` quedó NULL en las 280 Unidades Vecinales | El `MERGE` hacia Bronce nunca escribía esa columna | Corregido en la carga |
| Faltaban la caja de sanidad geográfica y la coincidencia exacta de coordenadas | La réplica omitió dos pasos del proyecto original | Se añadieron |
| Booleanos como `DOUBLE`; `solo_familias_texto` mal tipado | Inferencia de tipos al pasar por pandas | Booleanos a `INT`, texto a `STRING` |
| La imputación de superficie reinterpretaba el tipo de todas las columnas en cada corrida | Reescribía `avisos_limpios` completa vía pandas | `MERGE` dirigido solo a las filas y columnas que toca |
| `TABLE_OR_VIEW_NOT_FOUND` en tasas históricas | La vista temporal no se creaba si el caché ya cubría todo | Se crea siempre, vacía con esquema explícito |
| El `.pkl` del modelo no cargaba | Entrenado con numpy 2.x y el entorno serverless usa 1.23.5 | Alias de módulo `numpy._core` → `numpy.core` antes de deserializar. Pinear numpy/pandas rompía el arranque de Spark Connect |
| Mismo incidente del muro de verificación | Replicaba el scraper de Concepción | Se copió la detección de `bloqueado` y se descartó el marcado inmediato como `no_disponible` |
| Independencia entre sistemas | La población de referencia dependía de la base de Concepción | Se refrescó usando solo el Bronce propio |

---

## 3. Lecciones transversales

1. **Una respuesta vacía no es un éxito.** El patrón de los tres incidentes: el sitio entrega algo
   que parece válido y el pipeline lo toma como dato. Hay que distinguir "el sitio nos frena" de "este
   aviso no existe", y fallar fuerte en el primer caso.
2. **Nunca concluir "eliminado" por una sola señal.** Ni un canonical distinto ni un fetch fallido bastan.
3. **Capturar evidencia cruda y decidir después.** Los dos incidentes de estado se agravaron porque el
   veredicto se guardaba en el mismo lugar que el dato.
4. **El orden de los pasos en SCD2 importa**, y la fecha de vigencia debe ser la del evento, no la de
   ejecución.
5. **Mínimo privilegio y DDL versionado.** `CREATE TABLE IF NOT EXISTS` no cubre cambios de tipo ni
   `NOT NULL`.
6. **Sesgo de supervivencia en el entrenamiento:** entrenar solo con avisos activos sobrerrepresenta
   los caros. Hay que incluir finalizados y fechar por publicación.
7. **Fuga de datos:** cualquier variable calculada con la propia fila, o con una parte del target, infla
   las métricas. Un MAPE demasiado bueno es una alarma.

---

## 4. Referencia técnica para Silver: limpieza y tipado

Todo esto ocurrió en `modelamiento/01_ingenieria_variables/01_ingenieria_variables.py` (Concepción) y
en `02_plata/04_limpieza_plata_sql.py` (Databricks). Se anota con sus umbrales exactos porque son las
reglas que Silver tendrá que decidir si repite, ajusta o descarta para la Región Metropolitana.

### 4.1 Parseo de campos crudos

| Campo | Regla |
|---|---|
| Números en formato chileno | `.` es separador de miles y `,` es decimal. Se quita el punto y se reemplaza la coma por punto. En SQL, `TRY_CAST`, para tolerar vacíos sin romper la corrida |
| Booleanos | "Sí" → 1, "No" → 0, cualquier otro valor → NULL (`amoblado`, `admite_mascotas`, `condominio_cerrado`, `estacionamiento_visitas`, `solo_familias`, `piscina`, `quincho`, `conserjeria`, `ascensor`) |
| `amoblado` | Además se deriva del **título** con la expresión `amoblad[oa]\|amueblad[oa]`, y esa columna reemplaza a la del detalle |
| `fecha_publicacion` | El sitio muestra "Publicado hoy", "esta semana" o "hace N días/semanas/meses/años". "Hoy" = 0 días; "esta semana" = 3 días (punto medio del rango 1–6, marcada como precisión `aproximada_categoria`); "hace N" = N unidades exactas, asumiendo 30 días por mes y 365 por año. **En Santiago el texto se guarda crudo** y se resta a `scraped_at`, no a la fecha de hoy |
| `gastos_comunes` | Tres casos: con punto = miles reales; dígito suelto menor a 1.000 sin punto = placeholder "incluido" → 0; sin punto y 500.000 o más = outlier → NULL. Respaldo con "Gastos comunes desde $X" de la insignia |
| Puntos de interés | Cuántos hay dentro de **500 m** y la distancia del más cercano, por 11 subcategorías: paraderos, estaciones de metro, jardines infantiles, colegios, universidades, plazas, supermercados, farmacias, centros comerciales, hospitales y clínicas. En Santiago Bronce guarda los subtítulos crudos ("0 mins - 15 metros") y el radio se aplica en Silver |
| Moneda | CLP, UF (`CLF` en el JSON del detalle) y US$ |

### 4.2 Filtros y descartes

| Regla | Umbral | Efecto |
|---|---|---|
| Valores imposibles | dormitorios > 6, baños > 5, estacionamientos > 15 | Concepción descarta la fila; Databricks deja el valor en NULL |
| Registros incompletos | sin dormitorios, baños o `superficie_m2` | Se descarta la fila |
| Coordenadas fuera de región | caja lat −37,5 a −36,0 y lon −73,7 a −72,5 (Gran Concepción) | Se descarta la fila. Sin coordenadas **se conserva**. Es una coordenada equivocada, no un outlier de magnitud |
| Precio máximo | `precio_clp` > 8.000.000 | Se descarta: se asume venta mal clasificada como arriendo. Se aplica sobre el arriendo, **no** sobre el costo total |
| `piso_unidad` > 30 | reemplazo por el promedio de los pisos válidos | Probable año de construcción tipeado en el campo del piso |
| Superficie < 30 m² | umbral mínimo | Se trata como corrupta y se imputa (ver 4.3) |

### 4.3 Imputaciones

> **Dónde se imputa en `santiago-rentals`.** Esta tabla describe lo que hacían Concepción y Databricks. En Santiago **Silver no
> imputa** (conserva lo que dijo la fuente y marca anomalías, ver P-18 de la bitácora) y las imputaciones que sirven al modelo
> se hacen en **Gold**. El caso implementado es la antigüedad (decisión del 21-oct-2026, `gold/sql/020_aviso_entrenamiento.sql`):
> si el aviso no la trae o trae un valor fuera de 0 a 150 años, se completa con la mediana de los avisos con dato válido en el
> mismo punto (5 decimales, un edificio) y, si no hay, con la de los avisos a menos de ~150 m (al menos 3). La columna
> `antiguedad_origen` guarda de dónde salió el valor (`aviso`, `mismo_punto`, `vecinos` o `sin_dato`).

| Variable | Método |
|---|---|
| Amenities sin dato (`piscina`, `quincho`, `conserjería`, `ascensor`, `bodegas`, `gastos_comunes`) | 0 (ausencia = no tiene) |
| `piso_unidad` sin dato | 1 |
| Conteos de puntos de interés sin dato | 0 |
| Vulnerabilidad socioterritorial | Promedio de la comuna; si la comuna entera no tiene datos, promedio global |
| `barrio` | Barrio de la vivienda más cercana con barrio conocido (BallTree con distancia haversine, k = 1) |
| Superficie útil y total | `RandomForestRegressor` por tipo de propiedad, entrenado solo con filas con superficie ≥ 30 m². Predictores: dormitorios, baños y comuna (más superficie útil para estimar la total). Validación 80/20 con 200 árboles; modelo final con 300 árboles sobre el 100 % de las filas confiables; mínimo 20 filas para entrenar. Si falta, respaldo con `superficie_m2` de la grilla |
| `antiguedad_anos` | Cascada, siempre calculada sobre los valores **originales**: moda de avisos con la misma latitud y longitud exactas → mediana de vecinos en 200 m → mediana por tipo → mediana por comuna → mediana global |
| `condominio_cerrado` | Moda por coordenadas exactas; lo que siga sin dato pasa a falso |
| Moneda a CLP | UF con el valor de la **fecha de publicación** (mindicador.cl, con caché en la base y descarga en paralelo). Si falta la fecha, promedio de las fechas del dataset. US$ con tasa fija de 930 |

### 4.4 Variables derivadas

- **`costo_total_clp`** = `precio_clp` + `gastos_comunes` (target).
- **`precio_m2_sector_departamento`:** mediana del costo total por m² útil de otros departamentos en
  300 m (se excluye la propia fila), con filtro de outliers IQR × 3. Si no hay vecinos, mediana del grupo,
  y queda `tiene_comparables_cercanos = falso`.
- **`nivel_barrio`:** costo total por m² promedio de cada barrio, suavizado hacia la media general
  `(n × media + 20 × media_general) / (n + 20)`, agrupado en 5 niveles con cuantiles ponderados por
  cantidad de avisos. El diccionario se guarda en `niveles_barrio.json` para reutilizarlo en inferencia;
  un barrio nuevo recibe el nivel de la media general.
- **`ratio_total_util`** = superficie total / superficie útil.
- **Distancias haversine** al centro de la comuna y al centro de Concepción, con centros aproximados
  escritos a mano en el código.
- **Comuna:** las comunas con pocos avisos se agrupan en "otras comunas" y luego se codifica one-hot.
- Hay una función de variables derivadas adicionales (ratios por dormitorio, índice de amenities,
  interacciones) implementada pero **deshabilitada**: no se comprobó mejora frente al ruido de partición.

### 4.5 Orden de los pasos del pipeline

1. Cargar `avisos` + `avisos_detalle` (solo departamentos, con detalle, estados elegidos).
2. Descartar valores imposibles y registros incompletos.
3. Descartar coordenadas fuera de región (**antes** de cualquier paso que use coordenadas, porque una
   coordenada errónea ensucia también a sus vecinos).
4. Imputar vulnerabilidad y barrio, normalizar amenities, corregir piso.
5. Convertir a CLP, filtrar precio máximo, calcular `costo_total_clp`.
6. `nivel_barrio`, luego imputación de superficie, luego `precio_m2_sector`.
7. Imputar antigüedad y condominio, codificar comuna, derivar `amoblado`, completar superficies, ratio.

El orden importa: el target se calcula **después** del filtro de precio y **antes** de `nivel_barrio` y
`precio_m2_sector`, que lo usan.

---

## 5. Referencia técnica para Gold: dataset, features y modelo

### 5.1 Población de entrenamiento

- Solo departamentos en arriendo, con detalle scrapeado, en estado `activo`, `pausado` o `finalizado`.
- Los finalizados solo entran si su `fecha_publicacion_aprox` es de los últimos 3 meses. Un valor NULL de
  fecha **queda fuera**, por conservador.
- Tamaños de referencia en Concepción: 1.414 filas solo con activos; ~2.430–2.450 incluyendo finalizados
  recientes; 1.627 en el CSV histórico original.

### 5.2 Las 29 features finales (Concepción)

- **Físicas:** `superficie_util_m2`, `superficie_total_m2`, `ratio_total_util`, `banos`,
  `estacionamientos`, `bodegas`, `piso_unidad`, `ascensor`, `piscina`, `amoblado`, `conserjeria`,
  `condominio_cerrado`, `antiguedad_anos`.
- **Ubicación y mercado:** `precio_m2_sector_departamento`, `tiene_comparables_cercanos`, `nivel_barrio`,
  `distancia_centro_concepcion_m`, `distancia_centro_comuna_m`, y los conteos `cantidad_paraderos`,
  `colegios`, `supermercados`, `jardines_infantiles`, `universidades`, `plazas`, `farmacias`, `clinicas`.
- **Socioeconómicas (índice IGVUST / Registro Social de Hogares, por Unidad Vecinal):** `rank_nac`,
  `hog_uv`, `p_urbano`.
- **Excluidas a propósito:** `gastos_comunes` y `precio_clp` (fuga hacia el target).

El set cambia entre corridas (32 features en una, 29 en otra), así que se recalcula con cada
reentrenamiento y no se arrastra.

### 5.3 Selección de variables

41 candidatas → (1) fuera las de varianza cero → (2) 30 modelos XGBoost con K-Fold (5 folds), importancia
SHAP por fold, `stability_score = (1 / (1 + CV)) × % de modelos con importancia > 0` → (3) curva de MAE
validado en k features, con la **regla de 1 error estándar** → (4) se elimina un miembro de cada par con
correlación > 0,95, conservando el de mayor estabilidad.

### 5.4 Entrenamiento

- **Split:** estratificado por quintil de costo total, semilla 42, ~70 % train / 15 % validación / 15 %
  test (1.138 / 244 / 245 sobre 1.627 filas). En producción 85 / 15 con ~10 % del train reservado para
  early stopping.
- **Optuna:** 50 pruebas, K-Fold de 5 **solo sobre train**, minimizando MAE; objective fijado a mano
  (`regression` L2 en LightGBM, `reg:squarederror` en XGBoost).
- **Espacio de búsqueda de LightGBM:** `learning_rate` 0,01–0,10 (log); `max_depth` 2–6; `num_leaves`
  8–64; `min_child_samples` 1–20; `subsample` 0,5–1,0; `colsample_bytree` 0,5–1,0; `reg_alpha` y
  `reg_lambda` 0,01–20 (log); `min_split_gain` 0–5. Early stopping de 50 rondas.
- **Ensamble de bagging:** 10 modelos con los mismos hiperparámetros y 10 semillas; la predicción es el
  promedio y la dispersión entre los 10 es la medida de confianza.
- **Validación opcional:** 8 particiones con semillas distintas y Optuna completo en cada una.
- **Línea base:** media del train (MAE 142.054) y "costo total por m² del sector × superficie" (MAE 93.161).
  LightGBM llegó a MAE 61.221, R² 0,794 y MAPE 9,92 %.
- **Error por quintil:** el MAE se concentra en el quintil más caro (Q5, ~120.000) aunque su MAPE (~12,6 %)
  no es dramáticamente peor; el más barato (Q1) tiene el MAPE más alto (~13,9 %).

### 5.5 Etiquetado oportunidad / caro

1. Error = costo total real − costo total predicho.
2. `z_robusto = (error − mediana_error_del_decil) / (MAD_del_decil × 1,4826)`, con el decil definido por el
   **costo total real**. Mediana y MAD porque cada decil tiene ~24–30 filas.
3. `oportunidad` si z < −1; `caro` si z > 1; `precio_de_mercado` en el resto.
4. Confianza: coeficiente de variación del ensamble, repartido en terciles (alta / media / baja).
5. Distribución obtenida en test: 66,1 % mercado, 19,2 % oportunidad, 14,7 % caro. Las oportunidades
   concentran más baja confianza (47 %) que las caras (39 %).
6. Los bordes de decil, mediana/MAD por decil y terciles se persisten (`parametros_produccion.json`).

### 5.6 Versionado y artefactos

Versión `v{n}_{fecha}_{algoritmo}_{hash}` archivada sin sobrescribir. Un reentrenamiento escribe tres
artefactos que la inferencia **vuelve a leer**: el CSV del dataset, `niveles_barrio.json` y los modelos de
imputación de superficie. Deben poder redirigirse en las corridas exploratorias, o se le cambia el
comportamiento al modelo desplegado sin querer.

---

## 6. Qué probablemente no se traspasa tal cual a la Región Metropolitana

Son hipótesis a validar al llegar a Silver y a Gold. Los números del sitio salen del HTML de Santiago ya
capturado.

| Elemento de Concepción | Por qué puede fallar en la RM |
|---|---|
| **Umbral de 30 m² como superficie "corrupta"** | En Santiago el filtro "30 m² útiles o menos" agrupa **1.224 de 4.308** avisos (28 %). Con ese umbral, el mercado de estudios y departamentos pequeños se tomaría por datos corruptos y se reemplazaría con una estimación |
| Precio máximo de 8.000.000 CLP | Las comunas más caras de la RM (Vitacura, Las Condes, Lo Barnechea) pueden tener arriendos reales cerca de ese tope. Revisar la distribución antes de aplicarlo |
| Caja geográfica del Gran Concepción | Hay que definir una caja para la RM (o por comuna), con el mismo criterio de descartar lo claramente erróneo |
| Centros de comuna escritos a mano y "distancia al centro de Concepción" | Reemplazar por los centros de las 23 comunas y por una referencia metropolitana, como el centro de Santiago |
| `COMUNAS_A_AGRUPAR` | La lista de comunas con pocos avisos es otra: Pedro Aguirre Cerda tiene 3 y Peñalolén 37 |
| IGVUST: ¿el shapefile cubre la RM? | **Verificado:** sí. El archivo es nacional y la RM tiene 1.369 Unidades Vecinales (52 comunas), cargadas a `bronze.igvust_uv` (ver P-18 de la bitácora). Un `rank_nac` más alto significa menor vulnerabilidad |
| Puntos de interés a 500 m | Con metro y mucho más comercio, el radio y las subcategorías pueden necesitar revisión. `estaciones_metro` no figuró entre las 29 features finales de Concepción |
| US$ a tasa fija 930 | Aceptable si los avisos en dólares siguen siendo un puñado; comprobarlo |
| Población de referencia y `nivel_barrio` | Con unos 15.000 avisos y 23 comunas, el tamaño y la estructura permiten otro esquema de validación (por ejemplo por comuna o por tiempo) |
| Variables derivadas deshabilitadas | Con más datos puede valer la pena volver a probarlas |

---

## 7. Cuidados detectados para las etapas siguientes

1. **`nivel_barrio` usa todos los datos, incluido el test.** Se calcula con el costo total de todos los
   avisos antes del split. El suavizado (k = 20) lo mitiga, pero el barrio codifica parte del target y
   puede inflar levemente las métricas. Conviene calcularlo solo con train.
2. **`precio_m2_sector` también se calcula con todo el dataset.** Excluye la propia fila, pero un vecino
   puede estar en test. Misma advertencia que el punto anterior.
3. **Sesgo de supervivencia y de tiempo.** Los finalizados reflejan lo que se arrendó, los activos lo que
   no. Con las SCD2 de Santiago se podrá medir cuánto estuvo publicado un aviso y cuál fue su último precio.
   El precio de un finalizado es **el último que se vio**, no necesariamente el de cierre.
4. **Fecha de publicación aproximada.** "Esta semana" es una convención de 3 días. En Santiago, la fecha
   se deriva de `scraped_at` y del texto crudo, con la misma lógica.
5. **Rebajas.** Un aviso puede aparecer con `original_value`. El precio vigente y el anterior son datos
   distintos y no hay que mezclarlos (en Concepción se mezclaron precio "Antes" con moneda "Ahora").
6. **Calidad de `gastos_comunes`.** Hereda errores de digitación y afecta directamente al target.
7. **Dataset chico.** En Concepción rondó 1.600 filas, y la validación multi-semilla existe porque el
   split afecta mucho a las métricas.
8. **Carpetas sincronizadas con Google Drive.** Concepción perdió 25 filas de una migración de SQLite en
   una carpeta sincronizada (el repo vivía en `G:\Mi unidad`). `santiago-rentals` usa Postgres, pero
   conviene mantener fuera de una carpeta sincronizada el `landing/`, que escribe miles de archivos.
9. **Proyectos inmobiliarios.** No eran un problema en Concepción. En la RM representan ~1 % de la grilla
   y se excluyen del dataset de entrenamiento.

---

## 8. Qué hereda y qué cambia `santiago-rentals`

| Tema | Concepción | Databricks | `santiago-rentals` |
|---|---|---|---|
| Alcance | Gran Concepción, operativo | Réplica operativa | Región Metropolitana, solo captura (Bronce) |
| Almacenamiento | Postgres, un nivel | Delta, tres capas | Postgres, esquema `bronze` (Silver y Gold después) |
| Orquestación | GitHub Actions | Workflows de Databricks | Local, tarea programada de Windows |
| Bronce | Mutable | Append-only, todo `STRING` | Append-only, con hash para no repetir observaciones |
| Control de reintentos | Contador mutable | Log append-only | Log append-only (`detalle_intentos`) |
| Estado y precio | Columna mutable | Re-chequeo en Oro | Evidencia cruda por visita en Bronce; interpretación en Silver |
| Historial (SCD2) | No hay | En Oro, `valid_from` = hora de ejecución | En Gold (como en Databricks), derivado de la historia de observaciones de Silver con la fecha real de observación y reconstruible |
| Defensa de bloqueo | Agregada tras dos incidentes | Copiada de Concepción | Desde el diseño: muro, CAPTCHA, página 1 vacía, fallos seguidos |
| Casas | Se scrapean sin puntuar | No | No se scrapean |
| Proyectos inmobiliarios | No tratados | No tratados | Detectados (`proyecto`) y excluidos de la cola |
| Imputación de la antigüedad | Cascada en la ingeniería de variables | En Plata | **En Gold** (21-oct-2026): mismo punto y luego vecinos a ~150 m; Silver no imputa y `antiguedad_origen` guarda el origen del valor |
| Meta | Dashboard y producción | Producción | Datos limpios en Gold para **entrenar** un modelo |
