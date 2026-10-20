import { fileURLToPath } from "node:url";

import { construir, nota } from "./lib.mjs";

const DESTINO = fileURLToPath(new URL("..", import.meta.url));  // docs/diagramas/

await construir({
  archivo: "elt-arquitectura",
  destino: DESTINO,
  pagina: "Arquitectura del ELT",
  nodos: [
    { key: "portal", shape: "rect", label: "Portal Inmobiliario", color: "Externo", x: 20, y: 215, w: 230, h: 90 },
    { key: "grilla", shape: "rect", label: "Scraper de grilla", color: "Servicio", x: 340, y: 120, w: 230, h: 90 },
    { key: "detalle", shape: "rect", label: "Scraper de detalle", color: "Servicio", x: 340, y: 310, w: 230, h: 90 },
    { key: "bronce", shape: "cylinder", label: "Bronce", color: "Almacén", x: 700, y: 205, w: 210, h: 110 },
    { key: "landing", shape: "cylinder", label: "Landing (HTML)", color: "Cache", x: 700, y: 440, w: 210, h: 100 },
    { key: "silver", shape: "cylinder", label: "Silver", color: "Datos", x: 1040, y: 205, w: 210, h: 110 },
    { key: "mindicador", shape: "rect", label: "mindicador.cl", color: "Externo", x: 960, y: 440, w: 190, h: 80 },
    { key: "igvust", shape: "rect", label: "IGVUST", color: "Externo", x: 1190, y: 440, w: 150, h: 80 },
    { key: "gold", shape: "cylinder", label: "Gold", color: "Datos", x: 1380, y: 205, w: 210, h: 110 },
    { key: "modelo", shape: "rect", label: "Modelo (repo ML)", color: "IA", x: 1380, y: 400, w: 230, h: 90 },
    { key: "pred", shape: "cylinder", label: "gold.predicciones", color: "Éxito", x: 1380, y: 560, w: 230, h: 100 },
    nota("n_grilla", 320, 20, 290, 66, "12 comunas; si pasan de 1.800\nresultados, se parte por precio"),
    nota("n_detalle", 300, 440, 330, 66, "Cola: nuevo, desaparecido, tarjeta\ncambiada y rotación por antigüedad"),
    nota("n_bronce", 680, 80, 250, 66, "Registro crudo:\nsolo se agrega"),
    nota("n_silver", 1020, 80, 250, 66, "Limpia y marca banderas\nde anomalía"),
    nota("n_gold", 1360, 80, 250, 66, "Aptos para entrenar:\nsin banderas"),
  ],
  aristas: [
    { from: "grilla", to: "portal", label: "lista" },
    { from: "detalle", to: "portal", label: "visita" },
    { from: "grilla", to: "bronce", label: "tarjetas" },
    { from: "detalle", to: "bronce", label: "observación" },
    { from: "bronce", to: "landing", label: "HTML" },
    { from: "bronce", to: "silver", label: "limpia" },
    { from: "mindicador", to: "silver", label: "UF, dólar" },
    { from: "igvust", to: "silver", label: "UV" },
    { from: "silver", to: "gold", label: "aptos" },
    { from: "gold", to: "modelo", label: "datos" },
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
