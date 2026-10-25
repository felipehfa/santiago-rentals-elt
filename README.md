# santiago-rentals-elt

Repo del **ELT** (scrapers, Bronce, Silver y Gold). El modelo vive en el repo hermano
`santiago-rentals-ml`; el único punto de contacto es `gold.aviso_entrenamiento` en Supabase.

Captura de avisos de **arriendo de departamentos** de Portal Inmobiliario en la **Región Metropolitana**,
con arquitectura medallón (Bronce → Silver → Gold). El objetivo final es dejar en Gold datos limpios para
**entrenar un modelo** que estime el costo total mensual de un arriendo. Existen las tres capas (Bronce, Silver y Gold); el estado de cada pieza está en la tabla de abajo.

Los scrapers se ejecutan **de forma local** (no en GitHub Actions) y escriben a un proyecto Supabase
propio. La razón: el sitio bloquea las IPs de datacenter, y en el proyecto de Concepción eso pasó
inadvertido durante 17 días (ver `docs/01_antecedentes_concepcion_y_databricks.md`).

## Diagramas del proceso

Hechos con [Fluyo](https://fluyo.space). Cada diagrama es un `.svg` (la vista estática que se ve aquí) y un `.fluyo.json` en
`docs/diagramas/`; ese archivo se abre con el botón **Abrir** de fluyo.space para reproducir sus **Historias** (el orden en el
tiempo de un proceso, animado) y exportar un GIF. Los scripts que los generan están en `docs/diagramas/herramientas/` (ver su
`LEEME.md`). Van en el orden del proceso: la arquitectura general, la grilla, la cola del detalle, el orquestador, Silver, Gold y el recorrido de
un aviso.

### 1. Arquitectura del ELT

![Arquitectura del ELT](docs/diagramas/elt-arquitectura.svg)

El recorrido de un aviso desde el portal hasta su predicción, de izquierda a derecha:

- **Captura.** Dos scrapers visitan el portal. La *grilla* descubre qué avisos existen en las 12 comunas; el *detalle* visita cada
  aviso para leer su estado y su precio.
- **Bronce.** Registro crudo, al que solo se agrega: cada visita queda en `detalle_intentos` y una observación nueva solo si el
  aviso cambió. El HTML original queda aparte en *landing* (local, fuera de git).
- **Silver.** Limpia y une las fuentes: UF y dólar de mindicador.cl a la fecha del precio, y la unidad vecinal (IGVUST) de cada
  aviso. Marca banderas de anomalía.
- **Gold.** `aviso_entrenamiento` deja los avisos aptos para entrenar. Es el único punto de contacto con el repo del modelo, que
  devuelve sus predicciones a `gold.predicciones`.
- **Permisos.** `scraper_local` escribe en Bronce, `ml_lectura` lee Gold y `ml_scoring` lee Gold e inserta predicciones.

Historias: *Un aviso nuevo, de la publicación a la predicción* y *Un 429: espera y retoma con menos ritmo*.

### 2. Flujo de la grilla

![Flujo de la grilla](docs/diagramas/elt-grilla.svg)

Cómo se descubre qué avisos existen (`bronze/scraper_grilla.py`):

1. Para cada comuna de `config.COMUNAS_RM` pide la página 1 y lee el **total declarado** ("N resultados").
2. El sitio corta cada búsqueda en 2.016 resultados (responde 404 desde la página 43). Si el total supera **1.800**, la búsqueda se
   complementa con tres búsquedas por dormitorios (1, 2 y 3; el `robots.txt` del sitio impide partir por precio) y con la búsqueda
   sin filtro recorrida hasta el tope. Los duplicados se absorben por ID. Un filtro que aun así pasa de 2.016 (1 dormitorio en
   Santiago) deja avisos sin ver, y esa comuna queda con cobertura parcial.
3. Recorre las páginas de cada búsqueda y guarda el HTML y las tarjetas. Una tarjeta entra a Bronce **solo si cambió** (hash de su
   contenido, sin el `tracking_id` aleatorio de la URL).
4. Al cerrar cada comuna compara los avisos únicos capturados con el total declarado y registra su **cobertura**: `completa` si
   faltan menos de max(10, 1 %). Una corrida con alguna comuna `parcial` queda `parcial`.
5. **Bloqueo.** Con HTTP 403 o 429, o con 3 búsquedas seguidas cuya página 1 viene vacía sin que el sitio diga "0 resultados", la
   corrida se marca `bloqueado`: una respuesta vacía nunca es un éxito.

Historias: *Una comuna chica: sin partir*, *Santiago: más de 1.800, se complementa por dormitorios* y *El sitio bloquea la búsqueda*.

### 3. Cola y reglas del detalle

![Cola y reglas del detalle](docs/diagramas/elt-cola-detalle.svg)

Qué avisos visita el detalle y en qué orden (`bronze/scraper_detalle.py`). La cola se calcula con SQL, sin contadores mutables:

| Prioridad | Motivo | Condición |
|---|---|---|
| 1 | `nuevo` | Nunca se visitó con éxito |
| 2 | `desaparecido` | No apareció en la última corrida **completa de su comuna** y su última visita exitosa es de hace más de 2 días |
| 3 | `tarjeta_cambio` | Su tarjeta de la grilla cambió desde la última visita |
| 4 | `rotacion` | Pasó su intervalo de revisita, que depende de la antigüedad: cada 2, 4, 7, 14 o 30 días para avisos de hasta 14, 30, 60, 120 o más días |

Quedan **fuera**: los finalizados (terminal; un pausado sí se revisa), los ya clasificados como `proyecto`, los avisos de otras
comunas y los que acumulan 5 fallos o fallaron hace menos de 12 horas. Cada visita termina en `ok` (se guarda una observación si
el aviso cambió), `proyecto`, `no_encontrado`, `error` o un bloqueo. Bronce no interpreta: si un aviso está pausado o finalizado se
decide en Silver.

Historias: *Un aviso nuevo se visita primero*, *Un aviso desaparecido resulta ser un proyecto* y *Revisita por rotación y un 429*.

### 4. Orquestador del scraping

![Orquestador del scraping](docs/diagramas/elt-orquestador.svg)

Cómo se mantienen activos los dos scrapers sin intervención y qué hacen cuando el sitio los frena:

- **Orquestador.** Alterna *tandas* de 400 visitas del detalle y, cada 6 horas, la grilla, que entra a su hora aunque la cola
  del detalle sea larga. Si no hay nada que visitar, espera hasta 30 minutos y vuelve a mirar.
- **Detalle.** Recorre su cola con un presupuesto de visitas por ventana móvil de 24 horas y pausas aleatorias entre visitas
  (configurables; hoy de 3 a 6 s).
- **Silver y Gold.** Cada hora reconstruye Silver y luego Gold desde Bronce, entre tandas y también mientras corre una tanda
  de detalle (que puede pasar horas esperando por 429; ver P-26); nunca durante una grilla. Si falla, reintenta a los 30 minutos; el estado queda en `logs/silver_gold.json`
  y el error de Silver, en `silver.construcciones.detalle` (P-27: la base corta las sentencias a los 2 minutos, y Silver sube ese
  límite a 10 solo para su transacción).
- **Un 429.** El scraper no aborta: espera 30 minutos, duplica las pausas (hasta ×8) y las baja a la mitad cada 50 visitas
  buenas hasta volver a las originales. El ritmo con que termina una tanda se guarda y la siguiente lo retoma. Si 3 bloqueos
  seguidos no dejan avanzar, aborta y el orquestador espera 30, 60 o 120 minutos antes de relanzarlo.
- **Grilla.** Si el sitio la bloquea, reanuda solo las comunas que le faltaban. Una grilla incompleta no marca avisos como
  desaparecidos en las comunas que no cubrió.

Historias: *Una tanda de detalle y la grilla a su hora*, *Un 429 y la recuperación* y *La grilla bloqueada reanuda lo que
faltaba*.

### 5. Silver: limpieza y banderas

![Silver: limpieza y banderas](docs/diagramas/elt-silver.svg)

`silver/construir_silver.py` reconstruye `silver.avisos` completa desde Bronce, en una sola transacción (si algo falla, queda la
tabla anterior). No toca el sitio. Cada aviso toma su último estado y pasa por:

- **Tipado y monedas.** Pasa los textos a números y convierte el precio a CLP con la UF o el dólar del día de la visita (si ese
  día no hay valor, el anterior más cercano hasta 5 días atrás; más lejos queda en blanco y se marca).
- **Estado del aviso**, leído del texto del banner: sin texto es `activo`; "finaliz…" es `finalizado`; "pausad…" es `pausado`.
- **Fecha de publicación aproximada**: el texto relativo ("hace 13 días") restado a la fecha de la primera observación.
- **Banderas de calidad** (umbrales provisionales): superficie útil < 12 o > 500 m²; precio < 100 mil o > 8 millones; conteos
  imposibles (más de 6 dormitorios, 5 baños o 15 estacionamientos); sin coordenadas o fuera de la Región Metropolitana; gastos
  comunes faltantes; moneda sin valor de conversión.
- **Precio por m² atípico** (segunda pasada): el logaritmo del costo total por m² útil se compara con la mediana de su comuna con
  un z robusto (MAD); se marca si es mayor que 5. Las comunas con menos de 30 avisos usan la región entera.
- **Unidad vecinal.** Cada aviso con coordenadas se asigna a su unidad vecinal y recibe el índice socioeconómico (IGVUST). Solo
  se usan los polígonos de las comunas que se scrapean (385 de las 1.369 unidades de la Región Metropolitana que hay en Bronce) y
  el cruce es **incremental**: `silver.aviso_uv` guarda las coordenadas con que se asignó cada aviso y solo se cruzan los
  nuevos o los que cambiaron de coordenadas. El caché se descarta si se vuelve a cargar el archivo del IGVUST o cambia la lista
  de comunas. El archivo grande (el shapefile) no se lee en Silver: solo se lee al cargarlo a Bronce con `cargar_igvust.py`. Un
  aviso cuyas coordenadas caen en una comuna fuera de la lista (por ejemplo, una coordenada mal escrita) queda sin unidad vecinal
  y con la bandera `uv_sin_poligono`, en vez de recibir la de otra comuna.

Historias: *Un aviso normal, de Bronce a Silver* y *Un aviso con precio por m² absurdo*.

### 6. Gold: aptitud para entrenar

![Gold: aptitud para entrenar](docs/diagramas/elt-gold.svg)

`gold/construir_gold.py` lee solo Silver. Construye tres cosas:

- **`gold.aviso_entrenamiento`**: un aviso es **apto** si no tiene ningún motivo de exclusión. Los motivos se acumulan en
  `motivo_exclusion` para poder revisar qué descarta: proyecto, sin detalle, estado no reconocido, finalizado hace más de 90 días,
  sin precio, sin superficie, sin coordenadas, coordenada fuera de la región, conteo imposible, superficie sospechosa, precio
  sospechoso y precio por m² atípico. Incluye el título y la descripción, que usa el modelo, y la `url` de la publicación
  (la usa el mapa, para no leer Silver).
- **Antigüedad corregida:** si el aviso no trae `antiguedad_anos` o trae un valor imposible (fuera de 0 a 150), Gold la completa
  con la mediana de los avisos con dato válido en el mismo punto (5 decimales, un edificio) y, si no hay, con la de los avisos a
  menos de ~150 m (al menos 3). `antiguedad_origen` guarda de dónde salió (`aviso`, `mismo_punto`, `vecinos` o `sin_dato`). Medido
  dejando un aviso fuera: error mediano de 1 año en el mismo punto y 5,3 años de error medio con vecinos (7,8 con la mediana global).
- **`gold.dim_estado_aviso_scd2` y `gold.dim_precio_aviso_scd2`**: intervalos de vigencia del estado y del precio de cada aviso
  (con poca historia todavía: se llenan a medida que las revisitas acumulan cambios).
- **`gold.predicciones`** no se reconstruye: solo recibe filas del modelo.
- **`gold.modelo_vigente`** tampoco: el scoring escribe una fila por versión del champion con sus cifras (métricas, datos
  usados, variables que más pesan) y el mapa las lee para su pestaña "Cómo funciona". El DDL da los permisos a los roles
  `ml_scoring` (escribe) y `vis_lectura` (lee) si existen.

Historias: *Un aviso apto llega al modelo*, *Un aviso con superficie absurda queda fuera* y *Cada cambio queda con su vigencia*.

### 7. Recorrido de un aviso

![Recorrido de un aviso](docs/diagramas/elt-recorrido-aviso.svg)

Un solo aviso, de la página del sitio al mapa. Es la versión pensada para compartir: no nombra el portal.

- **Landing (staging).** El scraper de detalle visita el aviso y guarda su HTML crudo y comprimido (local, fuera de git), para
  poder volver a leerlo sin pedir otra vez la página.
- **Bronce.** Los campos extraídos entran como una fila nueva solo si cambiaron (hash del contenido).
- **Silver.** Tipa lo de Bronce, convierte UF y dólar a pesos con el valor del día, cruza la unidad vecinal (IGVUST) y marca las
  banderas de calidad.
- **Gold.** Completa la antigüedad faltante y deja el aviso apto (o con sus motivos de exclusión).
- **Consumo.** El modelo lee Gold y escribe `gold.predicciones`; el mapa lee Gold y las predicciones.

Historia: *Un aviso, de la página al mapa*.

## Estado actual

| Pieza | Estado |
|---|---|
| Landing (HTML crudo en disco) | Funcionando |
| Bronce: grilla | Funcionando. Primera carga completa de las 23 comunas; desde el 2026-10-19 se scrapean 12 |
| Bronce: detalle | Funcionando. Primera carga a medias: 13.035 de ~14.900 avisos con observación |
| Silver: `silver.avisos` | Funcionando (14.947 filas; se reconstruye completa desde Bronce) |
| Silver: `silver.aviso_observaciones` | Funcionando (una fila por cambio observado en el detalle; hoy 1 por aviso) |
| Nivel socioeconómico (IGVUST) | Funcionando: 1.369 Unidades Vecinales de la RM en Bronce; los 1.194 avisos con coordenadas cayeron dentro de una |
| Gold: SCD2 de estado y de precio | Funcionando; sin historia real todavía (1 intervalo por aviso). Probado con un historial simulado |
| Gold: `gold.aviso_entrenamiento` | Funcionando: 14.947 avisos, 12.597 aptos (1.912 aún sin detalle; el resto, ~440, excluidos por calidad). Incluye el título y la descripción del aviso, que usa el modelo |
| Gold: `gold.predicciones` | La escribe el scoring por lotes del modelo (rol `ml_scoring`, `INSERT` y `SELECT`): predicción, etiqueta de mercado (oportunidad / precio de mercado / caro) y banda de mercado. `gold.predicciones_vigentes` es la última de cada aviso |
| Modelo | Funcionando en el repo `santiago-rentals-ml` |
| Orquestador (`bronze/orquestador.py`) | Funcionando: alterna detalle y grilla con esperas ante un 429. Reconstruye Silver y Gold cada hora. Falta la tarea programada de Windows |

Cifras al 18-oct-2026 (cambian con cada corrida):

| Dato | Valor |
|---|---|
| Avisos distintos vistos en la grilla | ~14.900 |
| Comunas con cobertura completa | 23 de 23 (Santiago: 4.299 de 4.299) |
| Visitas de detalle registradas | 4.584 (4.541 `ok`, 31 `proyecto`, 11 `no_encontrado`, 1 `bloqueado`) |
| Observaciones de detalle guardadas | 4.538 |
| Tamaño del schema `bronze` en Supabase | ~34 MB |
| HTML crudo en disco | ~660 MB |

## Arquitectura

El diagrama de la arquitectura está al inicio de este README (sección *Diagramas del proceso*). Las capas, de la
fuente al modelo:

### Capas

**Landing (`landing/`).** HTML crudo comprimido, local y fuera de git. Permite volver a parsear sin volver
a pedir las páginas. La grilla guarda cada página (`landing/<fecha>/<tipo>/<comuna>/pNNN.html.gz`, con una
subcarpeta `seg_<filtro>` cuando hay filtro de dormitorios). El detalle guarda el HTML solo cuando entra una
observación nueva (`landing/detalle/<fecha>/<id>.html.gz`).

**Bronce (Supabase, schema `bronze`).** Datos tal como vienen del sitio: sin limpiar, sin convertir
monedas, sin interpretar estados. Es **solo de inserción**: ninguna fila se actualiza. Los strings crudos
se guardan como `jsonb`.

| Tabla | Rol |
|---|---|
| `runs` | Una fila por ejecución de un scraper (inicio, fin, estado, páginas, filas) |
| `grilla_paginas` | Una fila por página pedida: URL, HTTP, tarjetas, total declarado, ruta del HTML, filtro de dormitorios. Es el log de auditoría |
| `grilla_avisos` | Tarjetas de la grilla. Se inserta una fila **solo si cambió** (hash del payload) |
| `grilla_vistos` | Primera y última vez que un aviso apareció en la grilla (permite detectar desaparecidos) |
| `grilla_cobertura` | Por comuna y corrida: total declarado, avisos únicos capturados y si quedó `completa` o `parcial` |
| `detalle_intentos` | Una fila por visita a un aviso, con su resultado. De acá se deriva la cola de pendientes |
| `detalle_avisos` | Observaciones del detalle: evidencia cruda de estado y precio, más el resto de los campos. Solo si lo observado cambió |

El DDL está versionado en `bronze/sql/` (`001_schema`, `002_detalle`, `003_cobertura`) y se aplica con
`scripts/aplicar_ddl.py`. Cada cambio de schema va en un archivo nuevo.

## Flujo de la grilla (`bronze/scraper_grilla.py`)

1. Para cada comuna de `config.COMUNAS_RM` pide la página 1 y lee el total declarado ("N resultados").
2. Si el total supera **1.800**, la búsqueda se complementa con los filtros de dormitorios que el sitio permite
   (`/1-dormitorio/`, `/2-dormitorios/`, `/3-dormitorios/`) y con la búsqueda sin filtro hasta el tope.
   El sitio corta cada búsqueda en 2.016 resultados (página 42) y responde 404 desde la 43. Parte de una
   escalera de rangos y divide a la mitad cualquiera que siga siendo grande. Los bordes se solapan y los
   duplicados se absorben por ID.
3. Recorre las páginas de cada búsqueda, guarda el HTML y las tarjetas. Solo se usa el selector
   `li.ui-search-layout__item`; los de `div` también capturan publicidad.
4. Al cerrar cada comuna compara los avisos únicos capturados con el total declarado y registra la cobertura
   (`completa` si faltan menos de max(10, 1 %)). Una corrida con alguna comuna `parcial` queda `parcial`.
5. **Detección de bloqueo.** Si 3 búsquedas seguidas traen la página 1 vacía sin que el sitio diga "0
   resultados", o hay HTTP 403/429, aborta y marca la corrida `bloqueado`. Una respuesta vacía nunca es un
   éxito.

El hash de cada tarjeta excluye el fragmento de la URL (`url_fragmento`), que trae un `tracking_id` aleatorio
por request.

## Flujo del detalle (`bronze/scraper_detalle.py`)

Un solo script para la primera visita y las revisitas. La cola se calcula con SQL, sin contadores mutables,
y se ordena por prioridad:

| Prioridad | Motivo | Condición |
|---|---|---|
| 1 | `nuevo` | Nunca se visitó con éxito (más recientes primero) |
| 2 | `desaparecido` | No apareció en la última corrida **completa de su comuna** y su última visita exitosa es de hace más de 2 días |
| 3 | `tarjeta_cambio` | Su tarjeta de la grilla cambió desde la última visita |
| 4 | `rotacion` | Pasó su intervalo de revisita según la antigüedad del aviso (2, 4, 7, 14 o 30 días) |

**Reparación única (P-25):** el motivo `sin_precio` va justo después de `nuevo` y re-visita los avisos cuya última visita se hizo entre el
21-oct 14:42 y el 22-oct 07:05 (hora de Chile) y no trajo precio ni estado, porque el portal sirvió una página reducida a un
User-Agent que se identificaba. Está acotado a esa ventana, así que al volver a visitarlos salen de la cola y no hay bucle.

Quedan fuera de la cola los avisos cuyo último estado contiene "finaliz" (terminal; un pausado sí se
revisa), los que ya se clasificaron como `proyecto`, y los que acumulan 5 fallos seguidos o fallaron hace
menos de 12 horas.

**Qué guarda cada visita exitosa:** el texto crudo del banner de estado (`NULL` si el aviso está activo), el
precio vigente, su moneda (`CLP`, `CLF` = UF) y el precio original si hay rebaja, el canonical y el og:url,
y el resto de los campos (superficie, dormitorios, baños, coordenadas, barrio, descripción, gastos comunes,
amenities y los subtítulos crudos de puntos de interés). Bronce **no interpreta**: si un aviso está
pausado o finalizado se decide en Silver.

**Resultados posibles de una visita:** `ok`, `error`, `no_encontrado`, `captcha`, `bloqueado` y `proyecto`.

**Defensas contra falsos "eliminado":**

- El muro de verificación de cuenta se detecta por la URL final y aborta la corrida sin tocar ningún aviso.
- Un aviso solo se considera inalcanzable tras varios fallos entre corridas, nunca por uno solo.
- 8 fallos seguidos en una corrida la abortan como `bloqueado`.
- Si la base corta la conexión (por ejemplo, al suspender el equipo), el scraper **reconecta y repite la
  operación** (`common/db.py::ConexionResiliente`, con esperas de 5 a 180 s) en vez de abortar. Si no logra
  reconectar, cierra la corrida como `error`. La grilla hace lo mismo con sus escrituras.
- **Ante un 429 no aborta:** espera 30 minutos, duplica las pausas (hasta x8) y reintenta el mismo aviso. Anota
  cuántas visitas aguantó entre bloqueos (en `bronze.runs.detalle` y en el log) para estimar el umbral real de la IP.
  Cuando el sitio deja de bloquear, cada 50 visitas buenas seguidas las pausas bajan a la mitad hasta volver a las
  originales. Solo aborta como `bloqueado` si 3 bloqueos seguidos no dejan avanzar ninguna visita.
  El factor de pausa con que termina cada tanda se guarda en `logs/detalle_ritmo.json` y la tanda siguiente lo retoma (si
  fue hace menos de 2 horas), así la recuperación tras un 429 continúa entre tandas en vez de reiniciarse al ritmo base.
- **Rotación escalonada por antigüedad:** un aviso activo se vuelve a visitar cada 2, 4, 7, 14 o 30 días según tenga
  hasta 14, 30, 60, 120 o más días de publicado (`DIAS_ROTACION_TRAMOS`). La edad sale del texto de Bronce ("hace 13 días",
  "esta semana"…) más los días transcurridos; sin fecha cuenta como reciente. En la rotación va primero el más atrasado
  respecto de su intervalo. Son unas 3.200 visitas por día con todo al día, lo que cabe en el presupuesto junto a lo que
  trae la grilla. Hasta el 24-oct eran 1, 2, 4, 7 y 14 días (~6.200 diarias): la cola nunca se vaciaba, los avisos de más de
  60 días no se revisaban y solo el 10 % de las visitas de rotación encontraba un cambio real (P-29). Para el hash del
  detalle se ignora la frase "fue publicada el N de Mes" de una plantilla de corredor que cambia sola.
- **Presupuesto de visitas:** `--presupuesto-dia` (1.500 por defecto) limita las visitas de una ventana móvil de 24 h,
  contando todas las corridas. La rotación recorre primero lo visitado hace más tiempo, así que con presupuesto
  limitado el ciclo completo se reparte sin dejar avisos sin revisar.
- **Solo las comunas de `config.COMUNAS_RM`:** la cola excluye avisos de otras comunas (`--comunas` cambia la lista).
- **Log de avance:** además de la pantalla, cada corrida agrega sus líneas a `logs/detalle.log` (fuera de git).
  Cada 50 visitas escribe una línea `Avance: 150/1322 (11 %) | 8,3 visitas/min | observaciones nuevas 148 |
  sin leer 4 | resta ~2 h 20 min`. También quedan la cola inicial, cada aviso que no se pudo leer, las
  reconexiones y el resumen final. El avance exacto está además en `bronze.detalle_intentos`.
- **Log de la grilla:** `logs/grilla.log` (fuera de git), un resumen y no una línea por página: `INICIO`, una línea
  por comuna (`[ 3/23] providencia  480 de 530 declarados (90,6 %) | INCOMPLETA | 12 págs | 4 min 43 s`),
  `SEGMENTA` cuando complementa por dormitorios, `ALERTA` ante una página 1 vacía, un error de red o un filtro que
  pasa del tope del sitio, `ABORTADO` con el motivo y `FIN` con las comunas incompletas. Con `--detalle` agrega una línea
  por página para depurar. Los dos scrapers escriben a pantalla y a su archivo fijo; no hay un log por turno.
- Los **proyectos inmobiliarios** (que la grilla también lista como "Desde $X … N unidades disponibles")
  redirigen a una página de proyecto con otro ID. Se registran como `proyecto` y se excluyen; no sirven para
  el modelo.

## Decisiones de diseño

| Decisión | Motivo |
|---|---|
| Ejecución local, no GitHub Actions | El sitio bloquea IPs de datacenter. Probado el 2026-10-19 desde un runner (rama `prueba-actions`): los 3 pedidos redirigieron a `/gz/account-verification` |
| Solo departamentos en arriendo | Alcance del modelo |
| Bronce de solo inserción, con hash | Historial de cambios sin repetir lo que no cambió |
| Evidencia cruda, interpretación en Silver | Los incidentes de Concepción se agravaron porque el veredicto se guardaba junto al dato |
| La cola de detalle se deriva con SQL | Sin contadores mutables |
| "Desaparecido" se evalúa por comuna | Una corrida parcial no debe hacer parecer desaparecidos a los avisos de otras comunas |
| El precio vigente y el estado salen del detalle | La grilla solo aporta una señal barata de que algo cambió |
| Segmentar por dormitorios, no por precio | El `robots.txt` bloquea `_PriceRange_`, y también superficie, baños y estacionamientos. Cumplirlo cuesta cobertura: "1 dormitorio" en Santiago declara más de 2.016 y el sitio no deja partirlo, y los filtros de 4 o más dormitorios y de estudio no existen (redirigen a la búsqueda sin filtro) |
| User-Agent y ritmo | User-Agent de navegador: se probó uno que se identificaba (21-oct) y el portal sirvió una página sin precio ni estado (bitácora P-25), así que se volvió al anterior. El presupuesto queda en 5.000 visitas por 24 h (se probó 6.000 y 7.000 el 21-oct y llegó un 429 con 6.660 visitas en 24 h y 247 en la última hora): el primer 429 llegó con ~7.500, y con ese margen no se busca el límite |
| HTML crudo a disco | Reproducibilidad; Supabase gratis tiene 500 MB |
| Sin conversión de monedas ni de fechas relativas en Bronce | La fecha absoluta se calcula en Silver restando el texto a `scraped_at` |

## Estructura

```
santiago-rentals-elt/
├── config.py                  # comunas, URL base, headers, delays, ruta del landing
├── requirements.txt
├── .env                       # BD_STRING (dueño) y BD_STRING_SCRAPER (Session pooler de Supabase); no se versiona
├── common/db.py               # conexión a Supabase
├── bronze/
│   ├── scraper_grilla.py
│   ├── scraper_detalle.py
│   ├── orquestador.py         # alterna detalle y grilla, reconstruye Silver y Gold cada hora; espera y reanuda ante un 429
│   └── sql/                   # 001_schema, 002_detalle, 003_cobertura
├── pyproject.toml             # ruff (sintaxis y pyflakes) y pytest
├── tests/                     # HTML sintético, sin red ni base de datos (CI en .github/workflows/ci.yml)
├── scripts/
│   ├── aplicar_ddl.py         # aplica los .sql en orden (idempotente)
│   ├── vigilar_orquestador.ps1       # lanza el orquestador si no está corriendo (nunca dos)
│   ├── instalar_tarea_windows.ps1    # registra la tarea programada que llama al anterior
│   ├── spike_slugs.py         # verificó los slugs de las 23 comunas
│   └── spike_detalle.py       # verificó dónde viven estado y precio en el detalle
├── docs/
│   ├── 01_antecedentes_concepcion_y_databricks.md
│   └── 02_bitacora_problemas.md
├── landing/                   # HTML crudo (local, fuera de git)
├── logs/                      # logs de corridas largas (fuera de git)
├── silver/
│   ├── construir_silver.py    # DDL, UF y dólar, y reconstrucción de silver.avisos y aviso_observaciones
│   ├── asignar_uv.py          # cruce punto-en-polígono: Unidad Vecinal de cada aviso
│   └── sql/                   # 001_schema (funciones y tablas), 010_construir_avisos
├── gold/
│   ├── construir_gold.py      # DDL y reconstrucción de los SCD2 y del dataset, con chequeos de integridad
│   └── sql/                   # 001_schema, 010_scd2, 020_aviso_entrenamiento
├── datos_externos/igvust/     # shapefile del índice socioeconómico (128 MB, fuera de git)
```

Se scrapean 12 comunas centrales o de interés: Santiago, Ñuñoa, Providencia, Estación Central, San Miguel,
Independencia, Macul, La Florida, Recoleta, Huechuraba, Quinta Normal y Conchalí. Las otras 11 (Las Condes, Vitacura,
Lo Barnechea, La Reina, Peñalolén, Quilicura, Maipú, Puente Alto, San Bernardo, Cerrillos y Pedro Aguirre Cerda)
quedaron fuera el 2026-10-19, y sus datos se borraron de la base y de `landing/` el 2026-10-24 (P-28). Se cambian editando
`config.COMUNAS_RM`; si una comuna sale de la lista, Silver marca sus avisos con `fuera_de_alcance`.

## Uso responsable del portal

Proyecto personal y sin fines comerciales; los datos son de avisos públicos de Portal Inmobiliario. Lo que se hace para no
abusar del sitio:

- **Respeta su `robots.txt`.** Se revisó el 2026-10-21 contra todas las URLs que pide el scraper: la grilla (`_Desde_`) y el
  detalle (`_JM`) están permitidos; la partición por precio (`_PriceRange_`) no, y se dejó de usar.
- **User-Agent de navegador.** Uno que se identificaba con el proyecto y su contacto recibió del portal una página reducida, sin precio ni estado (bitácora P-25).
- **Páginas incompletas = error.** Si el portal responde una página sin los datos del aviso (`appProps`), la visita cuenta como
  fallo: no se guarda y, si se repite, frena la corrida como un bloqueo (P-25).
- **Ritmo acotado.** Pausas de 3 a 6 s entre peticiones, tope de 5.000 visitas de detalle por 24 h y espera de 30 minutos con
  menos ritmo ante un 429. Nunca intenta saltarse un bloqueo o el muro de verificación.
- **Poco dato personal.** No se leen nombres ni contactos de vendedores. El HTML crudo (`landing/`) queda solo en local.
- **Este repo es privado.** El mapa público (repo `santiago-rentals-vis`) solo muestra datos básicos, con la ubicación
  aproximada y el enlace a la publicación original.

## Cómo ejecutar

**Todo el ciclo, sin intervención:** `python bronze/orquestador.py` alterna detalle y grilla (detalle, grilla, detalle…),
con un presupuesto de 5.000 visitas de detalle por 24 h (`--presupuesto-dia`).
El detalle trabaja en tandas de 400 visitas (`--tanda`) y, entre tandas, el orquestador revisa si ya toca la grilla, que corre como máximo cada 6 horas (`--grilla-cada-horas`) aunque la cola del detalle sea larga. Si el detalle termina bloqueado, espera 30, 60 y luego
120 minutos y lo relanza; si la grilla es bloqueada, espera igual y reanuda solo con las comunas que faltaban. Si se agota
el presupuesto de 24 h, espera a que se libere. Las pausas entre peticiones son de 6 a 12 s (`--pausa-min/--pausa-max`).
Cada hora (`--silver-gold-cada-horas`) reconstruye Silver y Gold, también durante una tanda de detalle; si falla, reintenta
a los 30 minutos. Con menos de 50 visitas disponibles en el presupuesto no lanza una tanda (espera a que se libere).
Su registro es `logs/orquestador.log`; para detenerlo con calma se crea el archivo `logs/orquestador.stop`.

Cada scraper por separado:

Requisitos: Python con `requests`, `beautifulsoup4`, `lxml`, `psycopg2-binary` y `python-dotenv` (ver
`requirements.txt`), y un `.env` con `BD_STRING` (rol dueño) y `BD_STRING_SCRAPER` (rol `scraper_local`), connection strings del **Session pooler** de Supabase,
que funciona por IPv4).

```bash
python scripts/aplicar_ddl.py                              # crea o actualiza el schema bronze

python bronze/scraper_grilla.py                            # todas las comunas
python bronze/scraper_grilla.py --comunas quilicura-metropolitana --max-paginas 2   # prueba chica
python bronze/scraper_grilla.py --sin-bd                   # solo landing, sin escribir en Supabase

python bronze/scraper_detalle.py --limite 300              # visita hasta 300 avisos de la cola
python bronze/scraper_detalle.py --limite 20 --motivos nuevo
python bronze/scraper_detalle.py --comunas nunoa-metropolitana   # solo esas comunas (por defecto, config.COMUNAS_RM)
python bronze/scraper_detalle.py --limite 20000 --presupuesto-dia 1200   # el presupuesto manda sobre el límite

python bronze/cargar_igvust.py                             # una vez (o al actualizar el shapefile)
python silver/construir_silver.py                          # reconstruye Silver desde Bronce
python gold/construir_gold.py                              # reconstruye Gold desde Silver
```

Todo es **reanudable**: si una corrida se corta, volver a lanzar el mismo comando retoma desde la cola. El
PC debe quedar encendido y sin suspenderse durante las corridas largas. La primera carga completa del detalle son unos 15.000
avisos: con el ritmo medido (~8,7 visitas por minuto) son unas 29 horas. Al terminar ocuparán unos 2 GB de HTML en `landing/` y
~70 MB en Supabase.

**Mantenerlo corriendo sin depender de una sesión abierta.** `scripts/instalar_tarea_windows.ps1` (una sola vez) registra la
tarea `SantiagoRentalsOrquestador`: al iniciar sesión y cada 10 minutos ejecuta `scripts/vigilar_orquestador.ps1`, que lanza el
orquestador solo si no hay uno corriendo. Así se recupera tras un reinicio o una caída del proceso. Para detenerlo a propósito,
crear `logs/orquestador.stop` (la tarea no lo relanza mientras el archivo exista; borrarlo para reanudar). Desactivar la
suspensión del equipo sigue siendo manual. Quitar la tarea: `Unregister-ScheduledTask -TaskName SantiagoRentalsOrquestador`.

**Alertas.** El repo del mapa tiene un workflow `vigilante` que corre cada hora en GitHub y falla (con correo) si Gold lleva más de
3 horas sin reconstruirse, si el scoring se atrasó o si más del 5 % de Gold quedó sin precio aunque se visitó su detalle (el
síntoma de P-25); avisa aunque el notebook esté apagado (ver el README de `santiago-rentals-vis`).

## Pruebas y CI

`python -m pytest -q` (23 pruebas, menos de un segundo) cubre con HTML sintético la extracción del detalle (campos, JSON de la
página, precio, estado, hash sin campos volátiles, y que una página sin datos del aviso sea un error y no un éxito), la grilla
(URLs sin los filtros que el robots.txt bloquea, tarjetas, cobertura), la tanda mínima, cuándo toca reconstruir Silver y Gold y
que se revise también durante una tanda. Fija además dos acuerdos de uso responsable: el User-Agent de navegador y el tope de 5.000
visitas por 24 h. El workflow `ci` corre ruff (sintaxis y pyflakes) y pytest en cada push, con las versiones fijas de
`requirements.txt`; Dependabot (`.github/dependabot.yml`) propone las actualizaciones y mantiene al día las Actions, que están
fijadas por commit. No hay pruebas del SQL de Silver y Gold: necesitan una base Postgres de prueba (pendiente).

## Lo que falta

1. Terminar la primera carga del detalle por tandas.
2. Orquestador local (grilla y luego detalle) y tarea programada de Windows con reintento al reanudar.
3. **Roles de Postgres de mínimo privilegio (hechos el 18-oct-2026):** `scraper_local` (`SELECT`, `INSERT` y
   `UPDATE` en `bronze`; sin crear, borrar ni vaciar tablas), `ml_lectura` (`SELECT` sobre
   `gold.aviso_entrenamiento`) y `ml_scoring` (ese `SELECT` más `INSERT` en `gold.predicciones`). Se crearon en
   Supabase y el SQL no se conserva en el repo. Los scrapers usan `BD_STRING_SCRAPER`; Silver, Gold y las
   migraciones siguen con `BD_STRING` (rol dueño).
4. **Silver y Gold** ya existen (ver el estado de arriba). El orquestador (`bronze/orquestador.py`) encadena
   detalle y grilla y reconstruye Silver y Gold cada hora; falta revisar los umbrales de las banderas de calidad y de aptitud, que son provisionales.
5. **Validar los SCD2 con historia real**, cuando las revisitas acumulen varios días de cambios.
6. **Modelo:** vive en el repo `santiago-rentals-ml`. Target decidido: `costo_total_clp`. Las variables que
   dependen del split (`nivel_barrio`, `precio_m2_sector`, imputación de superficie) se ajustan solo con
   train. Detalle en `docs/01_decisiones.md` de ese repo.
7. **Repos separados (hecho el 2026-10-17):** este repo (ELT) corre local; el de modelo corre en GitHub Actions.
8. **Scoring por lotes** del modelo sobre `gold.predicciones` (ya creada: aviso, versión del modelo,
   costo estimado, fecha), con el rol `ml_scoring` que solo puede insertar en ella.
9. **Sin API pública** de datos ni de predicción: Bronce, Silver y Gold son privados.

Dónde ocurre cada cosa: **solo Bronce habla con el sitio**. La revisión de estado y precio de los avisos es
`bronze/scraper_detalle.py` (primera visita y revisitas, el mismo script). Silver y Gold nunca tocan
el sitio: leen lo que Bronce dejó. La única llamada externa fuera de Bronce es la de Silver a `mindicador.cl`
(UF y dólar).

## Documentación

- `docs/diagramas/`: diagramas de proceso hechos con Fluyo (ver la sección *Diagramas*).
- `docs/01_antecedentes_concepcion_y_databricks.md`: arquitectura, decisiones y problemas de los dos
  proyectos anteriores, con la referencia técnica de limpieza, features y modelo para Silver y Gold.
- `docs/02_bitacora_problemas.md`: problemas de este proyecto y cómo se resolvieron. Se actualiza con
  cada problema nuevo.
- Las decisiones de la etapa de modelo (MLflow, CI/CD, scoring por lotes, sin API) están en
  `docs/01_decisiones.md` del repo `santiago-rentals-ml`.

## Antes de mover esta carpeta a otro repo

- `landing/` y `logs/` quedan fuera de git por el `.gitignore` de esta carpeta, pero ocupan espacio en disco
  y no deben ir a una carpeta sincronizada.
- El `.env` con `BD_STRING` no se versiona; en el repo nuevo hay que volver a crearlo a mano (lleva `BD_STRING` y `BD_STRING_SCRAPER`, connection strings del Session pooler).

## Licencia

[MIT](LICENSE).
