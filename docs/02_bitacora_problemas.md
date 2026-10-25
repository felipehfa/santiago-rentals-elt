# Bitácora de problemas de `santiago-rentals`

Registro cronológico de los problemas que aparecen y cómo se resuelven. Se agrega una entrada nueva al
final cada vez que algo falla, sorprende o obliga a cambiar una decisión. Las entradas no se reescriben:
si un problema cambia, se anota una actualización dentro de la misma entrada.

Cada entrada tiene: **Síntoma**, **Causa**, **Resolución** y **Estado** (`resuelto`, `abierto` o
`mitigado`). Las fechas son de 2026.

Contexto de las decisiones de diseño en `01_antecedentes_concepcion_y_databricks.md`.

---

## Resumen

| ID | Fecha | Problema | Estado |
|---|---|---|---|
| P-01 | 17-oct | Carpeta del proyecto creada en dos lugares | mitigado |
| P-02 | 17-oct | Selector de tarjetas sobrecontaba avisos (53 en vez de 48) | resuelto |
| P-03 | 17-oct | El hash de cada aviso cambiaba en cada request | resuelto |
| P-04 | 17-oct | Santiago supera el tope de paginación del sitio (2.016) | resuelto (4.299 de 4.299) |
| P-05 | 17-oct | La segmentación por dormitorios propuesta no alcanzaba | resuelto |
| P-06 | 17-oct | Proyectos inmobiliarios clasificados como avisos eliminados | resuelto |
| P-07 | 17-oct | Regex de proyecto demasiado estricto | resuelto |
| P-08 | 17-oct | La cola de detalle empezaba por proyectos | resuelto |
| P-09 | 17-oct | La lógica de "desaparecido" dependía de la última grilla global | resuelto |
| P-10 | 17-oct | Reconstrucción de cobertura omitió 3 comunas | resuelto |
| P-11 | 17-oct | Rutas de estado y rebaja sin verificar en una página real | resuelto, con un caso abierto |
| P-12 | 17-oct | Totales por segmento de precio no cuadran con los del sitio | abierto |
| P-13 | 17-oct | Intentos mal marcados `no_encontrado` quedan en el log | mitigado |
| P-14 | 17-oct | El entorno bloqueó copiar y borrar archivos entre carpetas | mitigado |
| P-15 | 17-oct | `bodegas` traía el valor `242085` en vez de una cantidad | resuelto en Silver |
| P-16 | 17-oct | El SCD2 se había planteado en Silver y debe estar en Gold | resuelto (decisión corregida) |
| P-17 | 17-oct | Silver construida mientras Bronce sigue cambiando quedaba inconsistente | resuelto |
| P-18 | 17-oct | Verificar que el índice socioeconómico (IGVUST) cubra la RM e incorporarlo | resuelto |
| P-19 | 17-oct | El SCD2 no se podía validar porque aún no hay historia real | mitigado |
| P-20 | 17-oct | El scraper de detalle recibió HTTP 429 y se abortó solo | mitigado (19-oct) |
| P-21 | 17-oct | Un aviso con gastos comunes de 95 millones pasó los flags de Silver | resuelto (18-oct) |
| P-22 | 19-oct | El scraper de detalle abortó al suspenderse el equipo (conexión a la base cortada) | resuelto (19-oct) |
| P-23 | 19-oct | La grilla murió con `connection already closed` tras un error de red | resuelto (19-oct) |
| P-24 | 19-oct | GitHub Actions no puede scrapear el portal | confirmado (19-oct) |
| P-25 | 22-oct | Con el User-Agent identificado el portal sirve una página sin precio ni estado | abierto (scraper detenido) |
| P-26 | 22-oct | Silver se detuvo porque la API de UF y dólar no respondió | resuelto |

---

## P-01 · Carpeta del proyecto creada en dos lugares

- **Síntoma:** el `.env` con la conexión a Supabase estaba en `gran-concepcion-rentals/santiago-rentals/`,
  pero el proyecto se había creado como carpeta hermana en `c:\Proyectos personales\santiago-rentals\`.
- **Causa:** la instrucción se interpretó como una carpeta nueva al lado del repo; en realidad ya existía
  una dentro de él.
- **Resolución:** los archivos se recrearon dentro de la carpeta del usuario (`config.py`, `.gitignore`,
  `.env.example`, `scripts/spike_slugs.py`). La carpeta hermana sigue existiendo con el HTML del primer
  spike en `landing/_spike/` y se puede borrar a mano.
- **Estado:** mitigado (queda la carpeta duplicada).

## P-02 · Selector de tarjetas sobrecontaba avisos

- **Síntoma:** Vitacura y Lo Barnechea mostraban 53 tarjetas en la página 1, Macul y La Reina 49, pero
  una página trae 48 avisos.
- **Causa:** los selectores `div.ui-search-result__wrapper` y `div.andes-card` también capturan
  contenedores de publicidad y carruseles. El scraper de Concepción los usaba primero.
- **Resolución:** se usa solo `li.ui-search-layout__item`, que da 48 tarjetas con ID único en todas las
  comunas probadas.
- **Estado:** resuelto. Quien reutilice el parser de Concepción debe tener esto presente.

## P-03 · El hash de cada aviso cambiaba en cada request

- **Síntoma:** al repetir la corrida sobre las mismas comunas, se insertaron de nuevo todas las filas
  (40 de 40) aunque nada había cambiado.
- **Causa:** la URL de cada tarjeta trae un fragmento (`#polycard_client=...&tracking_id=...&position=...`)
  con un `tracking_id` aleatorio por request.
- **Resolución:** la URL se guarda sin fragmento y el fragmento va aparte en `url_fragmento`, excluido
  del hash (`CAMPOS_VOLATILES`). Se vaciaron las tablas de prueba y se repitió: segunda corrida con 0
  filas nuevas.
- **Estado:** resuelto. El mismo patrón se aplicó en el detalle con `fecha_publicacion_texto`, que
  avanza sola ("hace 3 días" pasa a "hace 4 días").

## P-04 · Santiago supera el tope de paginación del sitio

- **Síntoma:** Santiago declaraba 4.307 resultados pero la primera carga solo capturó 2.014.
- **Causa:** el sitio entrega hasta la página 42 (2.016 resultados) y responde 404 desde la 43.
- **Resolución:** las búsquedas que declaran más de 1.800 resultados se parten en rangos de precio
  (`_PriceRange_<min>CLP-<max>CLP`), con bisección si un rango sigue siendo grande. Nueva tabla
  `grilla_cobertura` compara avisos únicos capturados contra el total declarado. La corrida queda
  `parcial` si alguna comuna no cuadra.
- **Estado:** resuelto en código. El resultado de la primera corrida segmentada se anota abajo, en la
  actualización de esta entrada.

> **Actualización (17-oct, corrida #10):** la grilla de Santiago terminó con estado `success`:
> **4.299 avisos únicos de 4.299 declarados, cobertura `completa`**, en 110 páginas y con 2.291 filas
> nuevas (antes había 2.014). Rangos usados y totales declarados: $0–$300.000 (1.141), $300.000–$400.000
> (2.073, que superó el umbral y se partió en $300.000–$350.000 con 1.296 y $350.000–$400.000 con 1.008),
> $400.000–$500.000 (1.075), $500.000–$700.000 (527) y más de $700.000 (85). La segmentación funcionó sin
> intervención. En `grilla_vistos` quedan 4.303 avisos de Santiago, 4 más que los declarados (avisos que
> entraron y salieron entre corridas).

## P-05 · La segmentación por dormitorios no alcanzaba

- **Síntoma:** la propuesta inicial era segmentar Santiago por número de dormitorios.
- **Causa:** el filtro "1 dormitorio" declara 2.454 resultados, más que el tope de 2.016. Se descubrió al
  leer los filtros reales del sitio en el HTML ya guardado, sin pedir nada nuevo.
- **Resolución:** se cambió a rangos de precio. Los tres rangos que ofrece el sitio (hasta $300.000,
  $300.000–$400.000, más de $400.000) bajan de 2.016 y suman el total declarado.
- **Estado:** resuelto. Lección: verificar la propuesta contra los datos antes de prometerla.

## P-06 · Proyectos inmobiliarios clasificados como avisos eliminados

- **Síntoma:** en las primeras pruebas del scraper de detalle, 8 de 8 avisos devolvieron
  `no_encontrado` y la corrida se abortó como `bloqueado`.
- **Causa:** la grilla también lista **proyectos inmobiliarios** ("Desde $325.000 … 6 unidades
  disponibles"). Su URL redirige (301) a una página de proyecto con otro ID, y el chequeo de
  canonical/og:url, pensado para detectar avisos eliminados, los marcó como tal.
- **Resolución:** nuevo resultado `proyecto` en `detalle_intentos`, que no es fallo y saca al aviso de la
  cola. Los proyectos no sirven para el modelo (son rangos, no una unidad con un precio) y se excluyen en
  Silver.
- **Estado:** resuelto. Las defensas contra falsos "eliminado" evitaron que esto contaminara datos: la
  corrida se abortó sola tras 8 fallos seguidos.

## P-07 · Regex de proyecto demasiado estricto

- **Síntoma:** tras P-06 seguían 10 avisos como `no_encontrado`.
- **Causa:** el patrón del canonical de un proyecto exigía 6 o más dígitos. Algunos proyectos tienen IDs
  cortos (`12072-edificio-porvenir-nva`) o doble guion (`11473--imu-san-cristobal-nva`).
- **Resolución:** el patrón pasó a `\d+-+`. Se probó contra 4 canonicals de proyecto y 3 que no lo son.
- **Estado:** resuelto.

## P-08 · La cola de detalle empezaba por proyectos

- **Síntoma:** los primeros avisos "nuevos" de la cola eran casi todos proyectos, así que no se probó un
  aviso individual.
- **Causa:** sin orden dentro del grupo "nuevo", la base los entregaba por ID ascendente, y los IDs bajos
  son proyectos antiguos.
- **Resolución:** los nuevos se ordenan de más reciente a más antiguo (`id_aviso DESC`).
- **Estado:** resuelto.

## P-09 · "Desaparecido" dependía de la última grilla global

- **Síntoma:** detectado al diseñar la segmentación, antes de que causara daño.
- **Causa:** la cola consideraba desaparecidos los avisos no vistos en la última corrida de grilla
  exitosa. Una corrida parcial o de una sola comuna haría parecer desaparecidos a los avisos de todas las
  demás.
- **Resolución:** la comparación es por comuna, contra la última corrida que la cubrió completa
  (`grilla_cobertura.estado = 'completa'`).
- **Estado:** resuelto. La tanda de detalle ya en marcha no se afectó porque armó su cola en memoria
  antes del cambio.

## P-10 · Reconstrucción de cobertura omitió 3 comunas

- **Síntoma:** la cobertura de la primera carga solo tenía 20 de 23 comunas.
- **Causa:** se reconstruyó contando filas de `grilla_avisos` de esa corrida; las comunas ya cargadas por
  pruebas previas no insertaron filas (hash sin cambios) y quedaron fuera.
- **Resolución:** segunda inserción desde `grilla_paginas`, contando avisos únicos de todas las corridas.
- **Estado:** resuelto. Quedaron 22 comunas completas y Santiago parcial.

## P-11 · Rutas de estado y rebaja sin verificar en una página real

- **Síntoma:** los 5 avisos del spike de detalle estaban activos y sin rebaja, así que no aparecieron ni
  el banner de estado ni `original_value`.
- **Causa:** muestra sin casos de interés.
- **Resolución:** se leyeron, en solo lectura, avisos de la base de Concepción y se bajaron sus páginas.
  Estado: `components.item_status_message.body.text`, con "Publicación finalizada" confirmado en 3
  casos; un aviso finalizado responde 200 con su último precio. Precio: `components.price.price` con
  `value`, `currency_id` y `original_value` solo si hay rebaja, confirmado con 2 rebajas en CLP y una en
  UF (`CLF`).
- **Estado:** resuelto con un caso abierto: **no se encontró ningún aviso pausado** (0 de 40 al azar en la
  base de Concepción). Se guarda el texto crudo y la clasificación se decide en Silver.

## P-12 · Totales por segmento de precio no cuadran con los del sitio

- **Síntoma:** el rango $0–$300.000 declara 1.141 resultados, pero el enlace de ese rango en la página
  sin filtro decía 861. Dos mitades de un rango suman más que el rango: 1.296 + 1.007 = 2.303 contra
  1.894.
- **Causa:** parcial. Los bordes de los rangos son inclusivos y se solapan (231 avisos cuestan exactamente
  $350.000), y el sitio parece convertir los avisos en UF con redondeo. No explica por completo la
  diferencia de ~280 en el primer rango.
- **Resolución:** no se exige disjunción. Los duplicados se absorben por ID y la completitud se mide por
  avisos únicos contra el total declarado de la comuna.
- **Estado:** abierto. La causa exacta del inflado no se conoce.
- **Actualización (17-oct):** en la corrida completa el rango $300.000–$400.000 declaró **2.073**, contra
  1.894 en el enlace de la página sin filtro, y $0–$300.000 declaró 1.141 contra 861. Los totales de los
  segmentos no coinciden con los del enlace, pero la unión de todos los segmentos sí cubrió exactamente los
  4.299 avisos declarados, así que no afecta la completitud.

## P-13 · Intentos mal marcados `no_encontrado` quedan en el log

- **Síntoma:** 10 filas de `detalle_intentos` dicen `no_encontrado` para avisos que en realidad son
  proyectos.
- **Causa:** son de las pruebas de P-06 y P-07, antes de la corrección.
- **Resolución:** el log es de solo inserción y no se edita. Esos avisos se reintentan pasadas 12 horas y
  quedarán registrados como `proyecto`.
- **Estado:** mitigado.

## P-14 · El entorno bloqueó copiar y borrar archivos entre carpetas

- **Síntoma:** los comandos `cp` y `rm` para mover el proyecto de una carpeta a otra fueron rechazados.
- **Causa:** una regla de seguridad del entorno sobre archivos de origen sensible, al haber un `.env` en
  una de las carpetas.
- **Resolución:** los archivos se recrearon con la herramienta de escritura, sin tocar el `.env`.
- **Estado:** mitigado (ver P-01).

## P-15 · `bodegas` traía el valor 242085 en vez de una cantidad

- **Síntoma:** en el detalle, algunos avisos tenían `bodegas = 242085` (4 de 948) o `249` (1).
- **Causa:** no es un error del regex. La página misma muestra "Bodegas / 242085": es un código interno del
  sitio, el mismo que usa en sus filtros para "Sí" (por ejemplo `_FURNISHED_242085`), que significa "tiene
  bodega" sin decir cuántas. El `249` es probablemente un dato mal digitado.
- **Resolución:** Bronce guarda el valor tal cual. En `silver.avisos`, un conteo entre 0 y 20 es la cantidad
  real; `242085` marca `tiene_bodega = true` y deja `bodegas` en NULL; cualquier otro valor grande se
  descarta. En Concepción este caso podría haber pasado como un outlier enorme sin que nadie lo notara.
- **Estado:** resuelto.

## P-16 · El SCD2 se había planteado en Silver y debe estar en Gold

- **Síntoma:** confusión sobre dónde ocurre la revisión de estado y precio de los avisos y en qué capa va
  el historial (SCD2). Los documentos decían que el SCD2 se construía en Silver.
- **Causa:** al diseñar se mezclaron dos cosas: la **captura** de cada cambio (que es de Bronce) y el
  **modelado del historial** con vigencias (`valid_from`, `valid_to`, `is_current`). El proyecto de
  Databricks tiene los SCD2 en Oro, como dimensiones del modelo dimensional, y esa es la convención a seguir.
- **Resolución:** la revisión de avisos (primera visita y revisitas) vive en `bronze/scraper_detalle.py` y
  es lo único que habla con el sitio. Silver tipa lo que Bronce capturó y expondrá la historia como filas
  de observaciones, sin vigencias (`silver.aviso_observaciones`, pendiente). Gold construye los SCD2 desde
  Silver, respetando que Gold no lee de Bronce. Se corrigieron el README, `docs/01` y el comentario del
  DDL `002_detalle.sql`.
- **Estado:** resuelto. Pendiente: construir `silver.aviso_observaciones` y los SCD2 en Gold.

## P-17 · Silver construida mientras Bronce sigue cambiando quedaba inconsistente

- **Síntoma:** al construir Silver con la tanda de detalle corriendo, `silver.avisos` contaba 1.073 avisos con
  detalle y `silver.aviso_observaciones` tenía 1.078 observaciones.
- **Causa:** las dos tablas se reconstruyen en la misma transacción, pero con el aislamiento por defecto de
  Postgres (`READ COMMITTED`) cada sentencia ve lo que Bronce tiene en ese instante, y el scraper inserta
  filas nuevas entre una sentencia y otra.
- **Resolución:** la transacción de construcción parte con `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ`,
  que fija una sola instantánea de Bronce para todo el proceso. Tras el cambio: 1.081 avisos con detalle y
  1.081 con observación.
- **Estado:** resuelto. Aplica a cualquier construcción futura de Silver o Gold que lea mientras los
  scrapers escriben.

## P-18 · Incorporar el nivel socioeconómico del sector (IGVUST)

- **Síntoma:** en `docs/01` quedaba pendiente comprobar si el shapefile de vulnerabilidad cubría la Región
  Metropolitana, porque Concepción solo había usado 280 Unidades Vecinales.
- **Causa:** no se había mirado el archivo. Estaba en el repo de Concepción (`datos_vulnerabilidad/`) y en el
  de Databricks.
- **Resolución:** el shapefile es nacional (6.887 UV, 346 comunas, EPSG:3857). La RM tiene **1.369 UV en sus 52
  comunas**, sin geometrías inválidas ni valores nulos, y como texto pesan 3,4 MB. Se cargaron a
  `bronze.igvust_uv` (`bronze/cargar_igvust.py`, tabla de referencia estática que se reemplaza entera). Silver
  ubica cada aviso en su UV con un cruce punto-en-polígono con shapely (`silver/asignar_uv.py`) y copia a
  `silver.avisos` los campos `rank_nac`, `c_ig_com`, `c_ig_reg`, `c_ig_nac`, `pob_rsh_uv`, `hog_uv` y
  `p_urbano`. **Los 1.194 avisos con coordenadas cayeron dentro de una UV.** Un aviso sin polígono queda con
  NULL y la bandera `uv_sin_poligono` (Silver no imputa).
- **Cómo leer el índice:** un `rank_nac` más alto significa **menor vulnerabilidad** (La Pintana ~1.600, Las
  Condes ~6.840 de 6.887); el cuartil 4 es el menos vulnerable. `p_urbano` va de 0 a 100.
- **Detalles de diseño:** se usó shapely y no PostGIS para no depender de una extensión de la base, como en
  Concepción. El shapefile (128 MB) está en `datos_externos/`, fuera de git. Al reconstruir Silver, 010
  vacía la tabla y el cruce vuelve a llenar las columnas de UV dentro de la misma transacción.
- **Estado:** resuelto.

## P-19 · El SCD2 no se podía validar porque aún no hay historia real

- **Síntoma:** al construir los SCD2 de Gold, todos los avisos tenían un solo intervalo vigente, así que no
  se ejercitaba ninguna parte de la lógica de cambios.
- **Causa:** cada aviso tiene una sola observación; las revisitas que capturan cambios llegan con los días.
- **Resolución:** se probó con un historial simulado dentro de una transacción que se revierte (el script
  inserta observaciones falsas, construye y compara). Resultados: un aviso con activo → pausado → activo →
  finalizado dio los 4 intervalos de estado con las fechas de cada cambio; un precio que baja de 100.000 a
  90.000 dio 2 intervalos, y un aviso en UF cuyo equivalente en pesos cambia pero no su precio en UF dio uno
  solo. Los datos reales quedaron intactos. `gold/construir_gold.py` además verifica en cada corrida que cada
  aviso tenga exactamente un intervalo vigente y que los intervalos no tengan huecos ni solapes.
- **Estado:** mitigado. La validación con historia real llega cuando las revisitas acumulen cambios.

## P-20 · El scraper de detalle recibió HTTP 429 y se abortó solo

- **Síntoma:** el 17-oct-2026 a las 18:26 (hora local) el scraper de detalle terminó con `estado=bloqueado`
  tras 3.243 visitas (3.233 observaciones nuevas). Último intento: `bloqueado`, HTTP 429. Las visitas previas
  eran todas HTTP 200 y el ritmo de la última hora fue de ~495 visitas.
- **Causa:** el sitio limitó la tasa de peticiones (429 = demasiadas solicitudes), tras unas 3,25 horas
  seguidas a ~8,7 visitas por minuto. No se sabe si el límite es por volumen acumulado, por ritmo o por
  ventana de tiempo.
- **Resolución:** la defensa funcionó como se diseñó: un 429 cuenta como bloqueo, aborta la tanda y no marca
  ningún aviso como eliminado ni fallido por error. Quedan sin visitar los avisos pendientes de la cola. Pendiente:
  esperar un tiempo y reanudar con menos ritmo (delays más largos o pausas periódicas).
- **Actualización (17-oct, tras ~25 min de pausa):** se relanzó con los delays de siempre (3 a 7 s). Una tanda
  de prueba de 40 y otra de 1.250 visitas terminaron sin ningún 429; una tercera de 1.000 seguía en curso. El
  límite no reapareció con tandas de ~2,5 h separadas por pausas, pero sigue sin saberse si volvería en una
  corrida continua de más de 3 horas. Se mantiene abierto.
- **Actualización (19-oct):** los bloqueos volvieron, cada vez antes (1.611, 588, 113, 640, 253 y 355 visitas), lo que
  sugiere un contador acumulado por IP y no solo la velocidad. Se levantan solos en minutos u horas. Mitigación: el
  detalle ya no aborta; espera 30 min, duplica las pausas (hasta x8) y reintenta, y registra cuántas visitas aguantó
  entre bloqueos. Hay un presupuesto móvil de 24 h, y `bronze/orquestador.py` alterna detalle y grilla con esperas
  crecientes (30, 60 y 120 min) y reanuda la grilla solo con las comunas que faltaban. Revisar cada aviso una vez por
  semana exigiría ~1.800 visitas/día en las 12 comunas, más de lo que la IP ha aguantado: el umbral real se estima con
  los "aguantes" registrados en `bronze.runs.detalle`.
- **Estado:** mitigado; el umbral exacto sigue sin conocerse.

---

## P-21 · Un aviso con gastos comunes de 95 millones pasó los flags de Silver

- **Síntoma:** al perfilar `gold.aviso_entrenamiento` para el modelo, `MLC-4551416062` (Santiago, 54 m2, 2
  dormitorios) tenía `precio_clp` = 450.000 y `gastos_comunes` = 95.000.000, por lo que `costo_total_clp` era
  95,45 millones. El siguiente costo más alto es de 8,5 millones. Estaba marcado como apto.
- **Causa:** Silver solo valida el rango de `precio_clp` (`precio_sospechoso`); no hay validación análoga sobre
  `gastos_comunes`, que casi seguro es un error de captura del aviso (probablemente un cero de más o un
  valor ingresado en otro campo).
- **Resolución:** en el modelo (`santiago-rentals-ml`) se aplica una cota provisional de
  `costo_total_clp` <= 10.000.000 en `config.yaml`, que lo excluye. Falta lo correcto en el ELT: agregar una
  bandera `gastos_comunes_sospechosos` en Silver (por ejemplo, sobre un múltiplo del precio de arriendo o un
  máximo absoluto) y que Gold lo excluya de la aptitud.
- **Resolución definitiva (18-oct):** el caso es parte de una familia más amplia: avisos con superficie o gastos
  imposibles que los umbrales fijos no ven (12,0 m² no es "< 12"; 322 o 492 m² quedan bajo 500; también apareció
  un aviso con gastos de 12.000 millones). Silver tiene una bandera nueva, `precio_m2_atipico`: costo total por
  m² útil en logaritmo, comparado con la mediana de su comuna con MAD (z robusto > 5; comunas de menos de 30
  avisos usan la región). Gold la suma como motivo de exclusión `precio_m2_atipico`. Marca 149 avisos, 31 de
  ellos aptos hasta entonces; los 31 se revisaron a mano y eran todos errores de captura. El corte de 5 es
  deliberadamente holgado (con 3,5 marcaba 110 aptos y rozaba precios legítimos).
- **Estado:** resuelto. La cota de 10 millones en el modelo se mantiene como red de seguridad.

## P-22 · El scraper de detalle abortó al suspenderse el equipo

- **Síntoma:** la corrida 29 se cortó a los 4 minutos con `server closed the connection unexpectedly` y luego
  `connection already closed`; quedó en `en_curso` en `bronze.runs`. Se sospechó del rol nuevo `scraper_local`.
- **Causa:** el usuario suspendió el notebook y el servidor cerró la conexión, que el scraper mantenía abierta
  entre visitas sin reconectarse. Los dos roles tienen los mismos tiempos de inactividad y de consulta, así que
  no era el rol.
- **Resolución:** `common/db.py::ConexionResiliente` reabre la conexión y repite la operación (esperas de 5, 15,
  45, 90 y 180 s para dar tiempo a que vuelva la red). `scraper_detalle.py` la usa en todas sus operaciones.
  Probado matando la sesión desde el servidor (`pg_terminate_backend`): la operación se repitió sola. La corrida
  huérfana 29 se marcó `error` a mano. Queda sin tratar que, tras reanudar, las visitas HTTP pueden fallar unos
  segundos mientras vuelve la red y contar como fallos seguidos.
- **Estado:** resuelto para la base; abierto para el caso de red caída durante la suspensión.

---

## P-23 · La grilla murió con `connection already closed`

- **Síntoma:** a las 17:02 un error de red en Ñuñoa cortó también la conexión a la base; `cerrar_run` falló con
  `InterfaceError` y la corrida 37 quedó `en_curso`. Santiago ya estaba guardada (4.301 avisos).
- **Causa:** a diferencia del detalle, la grilla usaba una conexión simple (misma causa que P-22).
- **Resolución:** las cinco funciones de escritura de `scraper_grilla.py` pasan por `ConexionResiliente` (decorador
  `resiliente`). La corrida 37 se marcó `error` y se relanzó sin Santiago: 22 comunas, 43 min, 21 completas;
  Ñuñoa quedó en 98,3 % (1.442 de 1.467).
- **Estado:** resuelto.

---

## P-24 · GitHub Actions no puede scrapear el portal

- **Síntoma:** desde un runner de Actions, 3 pedidos a páginas de grilla (con los mismos encabezados que el
  scraper) devolvieron 302 a `/gz/account-verification`; desde el equipo local la misma petición da 200.
- **Causa:** el sitio bloquea o exige verificación a IPs de centros de datos.
- **Resolución:** los scrapers siguen locales. En Actions pueden correr Silver, Gold y el modelo, que no tocan el
  portal. No se intenta saltar la verificación. La prueba vive en la rama `prueba-actions` del repo.
- **Estado:** confirmado.

---

## P-25 · Con el User-Agent identificado el portal sirve una página sin precio ni estado

- **Síntoma:** desde las 14:00 del 21-oct el 100 % de las visitas de detalle (~3.400) quedaron sin `precio_valor` ni
  `estado_texto`, barrio ni puntos de interés, aunque el resultado figuraba como `ok`. En Gold los avisos `sin_precio`
  pasaron de 0 a 2.916 y los aptos activos de 14.634 a 12.349, así que el mapa perdió ~2.000 avisos. De madrugada llegaron
  además 429 seguidos.
- **Causa:** el 21-oct se cambió el User-Agent a uno que se identifica (nombre del proyecto y contacto). El portal responde 200
  pero con una versión reducida de la página: el JSON de estado trae `framework` y no `appProps`, de donde salen precio, estado,
  barrio y puntos de interés (348 KB contra 560 KB). Probado con el mismo aviso: User-Agent identificado, `compatible; +url` y
  navegador con sufijo del proyecto devuelven la versión reducida; un User-Agent de navegador (con o sin la cabecera `From`)
  devuelve la completa. La extracción tomaba la respuesta como válida, contra la regla de que una respuesta vacía nunca es éxito.
- **Resolución:** scraper detenido (`logs/orquestador.stop`) el 22-oct a las 07:05. Pendiente: decidir la política de
  User-Agent, rechazar como error toda página sin `appProps` (que no se guarde como observación ni cuente como visita buena),
  y reparar las ~3.400 observaciones sin precio para que Silver las ignore y la cola las vuelva a visitar.
- **Actualización (22-oct, mediodía):** el usuario indicó que no había autorizado ese cambio y pidió dejarlo como estaba. Se
  volvió al User-Agent de navegador anterior (`config.py`) y se reanudó el orquestador. No se agregó la cabecera `From` ni
  la validación de páginas sin `appProps`. Siguen sin precio las ~3.400 observaciones de ayer (Silver las toma como la última
  visita de cada aviso), a la espera de decidir su reparación.
- **Reparación (22-oct, con el visto bueno del usuario):** nuevo motivo de cola `sin_precio` en `scraper_detalle.py`, acotado a la
  ventana mala (21-oct 14:42 a 22-oct 07:05, hora de Chile); sin modificar ningún registro de Bronce. Al volver a visitarlos con el
  User-Agent restaurado, su última observación trae precio y Silver los recupera. En la cola quedaron 3.537 avisos, con
  prioridad justo detrás de los nuevos.
- **Prevención (22-oct, tarde):** `visitar()` marca como `error` toda página sin `appProps`: no se guarda como observación y,
  si se repite 8 veces seguidas, la corrida lo trata como un bloqueo (espera y baja el ritmo). El vigilante del mapa alerta si más
  del 5 % de Gold queda `sin_precio`. Con eso, lo del 21-oct se habría frenado en minutos y avisado en horas.
- **Estado:** mitigado; reparación en curso (se completa a medida que el scraper la recorre, dentro del tope de 5.000 visitas por 24 h).

---

## P-26 · Silver se detuvo porque la API de UF y dólar no respondió

- **Síntoma:** a las 06:00 del 22-oct `construir_silver.py` falló con `ReadTimeout` de mindicador.cl; Gold quedó 4,6 h sin
  reconstruirse (el orquestador reintenta entre tandas de detalle, y la tanda en curso estaba bloqueada por 429).
- **Causa:** `cargar_indicadores` hacía una sola llamada de 30 s y cualquier fallo de red abortaba toda la reconstrucción.
- **Resolución:** `silver/construir_silver.py` reintenta 3 veces y, si la API sigue caída, sigue con los valores ya guardados.
  `construir_avisos` ya aborta si algún precio en UF o USD queda sin indicador, así que no se calcula nada con un valor
  equivocado. El vigilante del repo del mapa debía avisar al cruzar las 3 horas (no se comprobó que haya llegado el correo).
- **Estado:** resuelto.

## P-27 · Silver fallaba la mitad de las veces por el límite de 2 minutos por sentencia

- **Síntoma:** el 23-oct `construir_silver.py` falló 5 de 10 veces (03:39, 04:36, 05:08, 08:13 y 10:11); Gold quedaba hasta
  1 h más atrasado. El log del orquestador solo decía "falló": la salida de Silver no se guarda (corre sin consola).
- **Causa:** la base tiene `statement_timeout = 2min` y la sentencia que construye `silver.avisos` (con las distancias a POIs,
  `poi_distancias`) ya tarda alrededor de eso con ~18.400 avisos. El error quedó en `silver.construcciones.detalle`
  (`canceling statement due to statement timeout`), que es donde mirar primero cuando Silver falla.
- **Resolución:** `construir_avisos` sube el límite a 10 minutos solo para su transacción (`SET LOCAL statement_timeout`).
- **Pendiente:** acelerar el cálculo de distancias (por ejemplo, con un índice espacial) para no depender del límite.
- **Estado:** mitigado.

## P-28 · Datos de comunas fuera de alcance que ya no se actualizaban

- **Síntoma:** 3.252 avisos de las 11 comunas que salieron de `config.COMUNAS_RM` el 19-oct seguían en Bronce, Silver y Gold
  (2.990 aptos) sin actualizarse; confundían los conteos (por ejemplo, "avisos de la grilla sin detalle").
- **Prueba previa:** el modelo ML ya las excluía (`datos.comunas_excluidas`). Una prueba local con el pipeline completo (selección
  de variables, Optuna y ensamble) sobre el mismo test mostró que incluirlas no mejora: el modelo solo con las 12 comunas tuvo
  MAE 1,1 % menor (IC95 −1,5 % a +3,8 %, no significativo) y fue mucho mejor en Huechuraba, donde los precios del sector
  oriente empujaban las estimaciones hacia arriba.
- **Resolución (24-oct, a pedido del usuario):** se borraron, en una transacción, los avisos que solo aparecieron en esas comunas
  (31.942 filas de Bronce, Silver y Gold; ninguna predicción) y las filas de cobertura y páginas de la grilla de esas comunas.
  En `landing/` se borraron 3.222 archivos (435 MB). Se conservó `bronze.igvust_uv` (polígonos de referencia de toda la región)
  y el único aviso que también apareció en una comuna considerada. Silver marca `fuera_de_alcance` por si otra comuna sale de la
  lista. Es irreversible: si una comuna vuelve, se scrapea desde cero.
- **Estado:** resuelto.

## P-29 · La rotación gastaba el presupuesto en avisos que no cambiaban

- **Síntoma:** desde que la grilla quedó al día, ~75 % de las visitas diarias eran de `rotacion` y pocas traían algo nuevo
  (por ejemplo, 11 de 50 en una tanda del 24-oct).
- **Análisis (revisitas del 22 al 24-oct, sin la ventana de P-25):**
  - Rendimiento por motivo: `desaparecido` encontró un cambio en el 90 % de las 820 visitas (casi todo, finalizados);
    `tarjeta_cambio` en el 43 % de 1.810 (484 cambios de precio); `rotacion` en el 21 % de 3.643, pero solo el 10 % era real.
  - En la rotación: 79 % sin cambio; 11 % ruido (una plantilla de corredor reescribe "fue publicada el 19 de Octubre" con la fecha
    del día); 7 % pasó a finalizado o pausado (83 de esos 259 ya habían salido de la grilla); 3 % otros cambios reales;
    0,2 % precio. Los cambios de precio los detecta la tarjeta de la grilla, y un finalizado no se pierde por revisar menos: solo
    se detecta más tarde. Visitar cada 2 o cada 5-7 días encontró cambios reales en la misma proporción (9-12 %).
  - Los intervalos (1, 2, 4, 7, 14 días) pedían ~6.200 visitas diarias de rotación sobre ~12.500 avisos activos, y caben ~3.200
    (de 5.000, ~1.800 van a lo que trae la grilla). La cola nunca se vaciaba (3.948 vencidos) y, como va primero el más
    atrasado respecto de su intervalo, los de 1 día ganaban siempre: los 2.500 avisos de más de 60 días no se habían revisitado.
- **Resolución:** `DIAS_ROTACION_TRAMOS = (2, 4, 7, 14, 30)` (~3.160 visitas diarias con todo al día) y el hash del detalle ignora la
  frase de fecha de esa plantilla (`RE_FECHA_PLANTILLA`; los avisos sin la frase dan el mismo hash que antes).
- **Estado:** resuelto; revisar en unos días que la cola de rotación se vacíe y el rendimiento real por visita.

---

## Cómo agregar una entrada

```
## P-NN · Título corto

- **Síntoma:** qué se vio.
- **Causa:** por qué ocurrió (marcar si es parcial o desconocida).
- **Resolución:** qué se hizo, con archivos y cifras.
- **Estado:** resuelto | abierto | mitigado.
```

Y una fila en la tabla de resumen.
