import { fileURLToPath } from "node:url";

import { construir, nota } from "./lib.mjs";

const DESTINO = fileURLToPath(new URL("..", import.meta.url));  // docs/diagramas/

await construir({
  archivo: "elt-arquitectura",
  destino: DESTINO,
  pagina: "Arquitectura del ELT",
  nodos: [
    { key: "portal", shape: "rect", label: "Portal Inmobiliario", color: "Externo", x: 40, y: 270, w: 220, h: 80 },
    { key: "grilla", shape: "rect", label: "Scraper de grilla", color: "Servicio", x: 400, y: 160, w: 220, h: 80 },
    { key: "detalle", shape: "rect", label: "Scraper de detalle", color: "Servicio", x: 400, y: 380, w: 220, h: 80 },
    { key: "bronce", shape: "cylinder", label: "Bronce", color: "Almacén", x: 760, y: 255, w: 220, h: 110 },
    { key: "landing", shape: "cylinder", label: "Landing (HTML crudo)", color: "Cache", x: 760, y: 560, w: 220, h: 100 },
    { key: "silver", shape: "cylinder", label: "Silver", color: "Datos", x: 1120, y: 255, w: 220, h: 110 },
    { key: "mindicador", shape: "rect", label: "mindicador.cl (UF y dólar)", color: "Externo", x: 1010, y: 580, w: 200, h: 70 },
    { key: "igvust", shape: "rect", label: "IGVUST (shapefile por UV)", color: "Externo", x: 1250, y: 580, w: 200, h: 70 },
    { key: "gold", shape: "cylinder", label: "Gold", color: "Datos", x: 1480, y: 255, w: 220, h: 110 },
    { key: "modelo", shape: "rect", label: "Modelo (repo ML)", color: "IA", x: 1840, y: 160, w: 220, h: 80 },
    { key: "pred", shape: "cylinder", label: "gold.predicciones", color: "Éxito", x: 1840, y: 380, w: 220, h: 100 },
    nota("n_grilla", 360, 20, 340, 78, "12 comunas. Si una búsqueda declara más de\n1.800 resultados se parte por rango de precio\n(el sitio corta en 2.016)."),
    nota("n_detalle", 360, 500, 340, 98, "Cola: nuevo, desaparecido, tarjeta cambiada y\nrotación (cada 1 a 14 días según antigüedad).\nFuera: finalizados, proyectos y avisos\ncon 5 fallos."),
    nota("n_bronce", 735, 100, 270, 78, "Registro crudo: solo se agrega.\nCada visita queda en detalle_intentos;\nuna observación nueva, si cambió."),
    nota("n_silver", 1100, 100, 360, 98, "Se reconstruye (REPEATABLE READ). Marca:\nsuperficie < 12 o > 500 m²; precio < 100 mil\no > 8 M; precio por m² atípico\n(z robusto > 5)."),
    nota("n_gold", 1470, 100, 340, 98, "Apto: con detalle, no proyecto, no finalizado\nhace más de 90 días, con precio, superficie y\ncoordenadas, y sin banderas de anomalía."),
    nota("n_roles", 1790, 540, 360, 98, "Roles: scraper_local escribe en Bronce;\nml_lectura lee Gold; ml_scoring lee Gold\ne inserta en gold.predicciones."),
  ],
  aristas: [
    { from: "grilla", to: "portal", label: "lista avisos" },
    { from: "detalle", to: "portal", label: "visita aviso" },
    { from: "grilla", to: "bronce", label: "tarjetas" },
    { from: "detalle", to: "bronce", label: "observación" },
    { from: "bronce", to: "landing", label: "HTML crudo" },
    { from: "bronce", to: "silver", label: "limpia" },
    { from: "mindicador", to: "silver", label: "UF y dólar" },
    { from: "igvust", to: "silver", label: "UV" },
    { from: "silver", to: "gold", label: "aptos" },
    { from: "gold", to: "modelo", label: "aviso_entrenamiento" },
    { from: "modelo", to: "pred", label: "INSERT" },
  ],
  eventos: [
    { ref: "bloquea", name: "Bloquea (429)", primitive: "OCCURRENCE", sentence: "{target} bloquea la IP" },
    { ref: "espera", name: "Espera", primitive: "OCCURRENCE", sentence: "{target} espera 30 min y baja el ritmo" },
  ],
  historias: [
    {
      nombre: "Un aviso nuevo, de la publicación a la predicción",
      pasos: [
        { ev: "envia", de: "grilla", a: "portal", espera: 0 },
        { ev: "envia", de: "grilla", a: "bronce", tras: [0] },
        { ev: "envia", de: "detalle", a: "portal", espera: 600, tras: [1] },
        { ev: "envia", de: "detalle", a: "bronce", tras: [2] },
        { ev: "envia", de: "bronce", a: "landing", espera: 200, tras: [3] },
        { ev: "envia", de: "bronce", a: "silver", tras: [1, 3] },
        { ev: "procesa", nodo: "silver", tras: [5] },
        { ev: "envia", de: "silver", a: "gold", tras: [5] },
        { ev: "procesa", nodo: "gold", tras: [7] },
        { ev: "envia", de: "gold", a: "modelo", tras: [7] },
        { ev: "envia", de: "modelo", a: "pred", tras: [9] },
        { ev: "procesa", nodo: "pred", tras: [10] },
      ],
    },
    {
      nombre: "Un 429: espera y retoma con menos ritmo",
      pasos: [
        { ev: "envia", de: "detalle", a: "portal", espera: 0 },
        { ev: "bloquea", nodo: "portal", tras: [0] },
        { ev: "espera", nodo: "detalle", espera: 800, tras: [0] },
        { ev: "envia", de: "detalle", a: "portal", espera: 2500 },
        { ev: "envia", de: "detalle", a: "bronce", tras: [3] },
      ],
    },
  ],
});
