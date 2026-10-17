# Resumen de la conversación de construcción (hasta el 2026-10-17)

Punto de partida para retomar el trabajo en una sesión nueva. Complementa el [README](../README.md), la
[bitácora de problemas](02_bitacora_problemas.md) y los antecedentes
([01](01_antecedentes_concepcion_y_databricks.md)). Las decisiones de modelo están en
`docs/01_decisiones.md` del repo `santiago-rentals-ml`.

## 1. Objetivo

Capturar avisos de **arriendo de departamentos** de Portal Inmobiliario en la Región Metropolitana, con
arquitectura medallón (Bronce → Silver → Gold) sobre un Supabase propio, y dejar en Gold datos limpios para
**entrenar un modelo de ML**. Los scrapers corren **en local** (el sitio bloquea las IPs de GitHub Actions).

## 2. Repos

Desde el 2026-10-17 el proyecto está en dos repos hermanos bajo `C:\Proyectos personales\santiago-rentals\`:

| Repo | Contenido | Dónde corre |
|---|---|---|
| `santiago-rentals-elt` | Scrapers, Bronce, Silver, Gold, documentación de datos | Local |
| `santiago-rentals-ml` | Modelo (features, entrenamiento, MLflow, gate, scoring) | Local al inicio, luego GitHub Actions |

Punto de contacto: `gold.aviso_entrenamiento` en Supabase. La carpeta vieja
`gran-concepcion-rentals\santiago-rentals\` ya no contiene el proyecto (solo `databricks/` y un `modelo/`
vacío, ambos borrables).

## 3. Estado de los datos (17-oct-2026)

- **Grilla:** terminó. Primera carga completa de las 23 comunas, y Santiago segmentada por rango de precio:
  4.299 de 4.299 avisos (`grilla_cobertura` en estado completa).
- **Detalle:** primera carga a medias. ~3.280 avisos visitados, ~10.300 pendientes (incluye ~2.300 nuevos de
  Santiago). Ritmo medido: ~8,2–8,7 visitas por minuto. La corrida se **abortó sola a las 18:26 con HTTP 429**
  (P-20, abierto) tras 3.243 visitas seguidas. No hay ningún scraper corriendo.
- **Silver y Gold** existen y se reconstruyen con `silver/construir_silver.py` y `gold/construir_gold.py`
  (`REPEATABLE READ`). Incluyen el nivel socioeconómico IGVUST (1.194/1.194 avisos con unidad vecinal).
- El SCD2 se validó con historial simulado; falta validarlo con historia real (revisitas).
- Observaciones de estado: 2 avisos con "Publicación finalizada" y 0 pausados hasta ahora.

## 4. Decisiones del ELT (resumen; el detalle está en README y docs)

- Bronce solo inserciones con hash; Silver sin descartar filas (flags); **SCD2 siempre en Gold**.
- UF y dólar a la fecha de observación del precio, guardando la moneda original (mindicador.cl).
- Proyectos inmobiliarios excluidos. `bodegas = 242085` es un código del sitio, no una cantidad.
- Segmentación por rango de precio cuando una búsqueda declara más de 1.800 resultados (tope del sitio:
  2.016). La completitud se mide por avisos únicos contra el total declarado.
- Cola de detalle derivada con SQL: motivos `nuevo`, `desaparecido` (por comuna contra la última cobertura
  completa), `tarjeta_cambio` y `rotacion` (7 días).
- Orquestador local y tarea programada de Windows: **pospuestos** por decisión del usuario.

## 5. Decisiones de modelo (resumen)

- Target: `costo_total_clp`. Modelos: XGBoost y LightGBM de Concepción, cada uno con Optuna.
- Arquitectura del webinar `jcbf08/Webninar_SDC_mlflow` (train → tune → register → promote → predict, con
  `@challenger` y `@champion`), con correcciones: seleccionar por validación cruzada y no por test, dos
  modelos, métricas de regresión.
- MLflow local primero; después Postgres y Storage de Supabase. CI y entrenamiento con datos reales vía rol de
  solo lectura. **Sin API pública**: scoring por lotes que escribe en `gold.predicciones`.
- Docker: no al inicio.

## 6. Pendientes

1. **Reanudar el detalle** observando si el 429 reaparece. Propuesta: esperar un rato, delays de ~6–12 s,
   pausas periódicas (p. ej. 10 minutos cada 300 visitas) y backoff ante 429 en lugar de abortar. Con ese
   ritmo los ~10.300 pendientes serían ~35–40 h. **Decisión del usuario: ver si el 429 aparece de nuevo, e
   iniciar en un rato.**
2. Crear la tabla `gold.predicciones` y el rol Postgres con `INSERT` solo en ella.
3. Rol Postgres `scraper_local` de mínimo privilegio y rol de solo lectura para el modelo.
4. Orquestador local y tarea programada de Windows (pospuesto).
5. Revisar umbrales provisionales de flags de calidad y de aptitud; validar el SCD2 con historia real.
6. Política de retención del `landing/` de grilla.
7. Repo de modelo: armar el esqueleto de la fase 1 (`config.yaml`, `Makefile`, `common.py`, `features.py`,
   tests).
8. Problema abierto P-12: los totales por segmento de precio no cuadran con los del sitio (no afecta la
   completitud).

## 7. Reglas del usuario

- Responder en español. **Nunca `git commit`/`git push`**; sin `Co-Authored-By`. Entorno conda `data-science`.
- No pegar el `.env` ni `BD_STRING` en el chat.
- Llevar la bitácora de problemas al día en el mismo turno.
- No lanzar scrapers sin que lo pida.

## 8. Cómo retomar

Abrir `santiago-rentals-elt` en VS Code, abrir una conversación nueva y pedir: "lee `CLAUDE.md`, el README y
`docs/03_resumen_conversacion_2026-10-17.md`, y reanuda el detalle". Para la etapa de modelo, abrir
`santiago-rentals-ml`.
