import { fileURLToPath } from "node:url";

import { construir, nota } from "./lib.mjs";

const DESTINO = fileURLToPath(new URL("..", import.meta.url));  // docs/diagramas/

await construir({
  archivo: "elt-orquestador",
  destino: DESTINO,
  pagina: "Orquestador del scraping",
  nodos: [
    { key: "orq", shape: "rect", label: "Orquestador", color: "Config", x: 20, y: 270, w: 220, h: 100 },
    { key: "detalle", shape: "rect", label: "Detalle (tandas)", color: "Servicio", x: 340, y: 120, w: 250, h: 90 },
    { key: "grilla", shape: "rect", label: "Grilla (cada 6 h)", color: "Servicio", x: 340, y: 440, w: 250, h: 90 },
    { key: "portal", shape: "rect", label: "Portal Inmobiliario", color: "Externo", x: 720, y: 280, w: 240, h: 90 },
    { key: "espera", shape: "rect", label: "Espera 30 min", color: "Alerta", x: 720, y: 20, w: 240, h: 80 },
    { key: "bronce", shape: "cylinder", label: "Bronce", color: "Almacén", x: 1100, y: 270, w: 210, h: 110 },
    nota("n_orq", 10, 420, 300, 88, "Alterna tandas de 400\nvisitas; la grilla entra\ncada 6 h"),
    { key: "sg", shape: "rect", label: "Silver y Gold (cada hora)", color: "Servicio", x: 1530, y: 275, w: 270, h: 90 },
    nota("n_sg", 1500, 410, 330, 88, "Entre dos tandas; si falla,\nreintenta a los 30 min"),
    nota("n_detalle", 320, 20, 330, 66, "Presupuesto: 5.000 visitas\npor 24 h"),
    nota("n_espera", 1090, 20, 340, 110, "429: pausas ×2 (hasta ×8)\ny vuelven a la mitad cada\n50 visitas buenas"),
    nota("n_grilla", 330, 560, 330, 66, "Si la bloquean, reanuda\nlas comunas que faltaban"),
  ],
  aristas: [
    { from: "orq", to: "detalle", label: "tanda" },
    { from: "orq", to: "grilla", label: "si toca" },
    { from: "detalle", to: "portal", label: "visita" },
    { from: "grilla", to: "portal", label: "páginas" },
    { from: "detalle", to: "bronce", label: "observación", fromSide: "e", toSide: "n" },
    { from: "grilla", to: "bronce", label: "tarjetas", fromSide: "e", toSide: "s" },
    { from: "bronce", to: "sg", label: "reconstruye", fromSide: "e", toSide: "w" },
    { from: "portal", to: "espera", label: "429" },
    { from: "espera", to: "detalle", label: "reintenta" },
  ],
  eventos: [
    { ref: "bloquea", name: "Bloquea (429)", primitive: "OCCURRENCE", sentence: "{target} bloquea la IP" },
    { ref: "espera", name: "Espera", primitive: "OCCURRENCE", sentence: "{target} espera y baja el ritmo" },
    { ref: "reanuda", name: "Reanuda", primitive: "OCCURRENCE", sentence: "{target} reanuda lo que faltaba" },
  ],
  historias: [
    {
      nombre: "Una tanda de detalle y la grilla a su hora",
      pasos: [
        { ev: "envia", de: "orq", a: "detalle", espera: 0 },
        { ev: "envia", de: "detalle", a: "portal", tras: [0] },
        { ev: "envia", de: "detalle", a: "bronce", tras: [1] },
        { ev: "procesa", nodo: "detalle", tras: [2] },
        { ev: "envia", de: "orq", a: "grilla", espera: 900, tras: [2] },
        { ev: "envia", de: "grilla", a: "portal", tras: [4] },
        { ev: "envia", de: "grilla", a: "bronce", tras: [5] },
        { ev: "envia", de: "orq", a: "detalle", espera: 900, tras: [6] },
      ],
    },
    {
      nombre: "Un 429 y la recuperación",
      pasos: [
        { ev: "envia", de: "detalle", a: "portal", espera: 0 },
        { ev: "bloquea", nodo: "portal", tras: [0] },
        { ev: "envia", de: "portal", a: "espera", tras: [0], espera: 300 },
        { ev: "espera", nodo: "espera", tras: [2] },
        { ev: "envia", de: "espera", a: "detalle", espera: 1500, tras: [2] },
        { ev: "envia", de: "detalle", a: "portal", tras: [4] },
        { ev: "envia", de: "detalle", a: "bronce", tras: [5] },
      ],
    },
    {
      nombre: "La grilla bloqueada reanuda lo que faltaba",
      pasos: [
        { ev: "envia", de: "orq", a: "grilla", espera: 0 },
        { ev: "envia", de: "grilla", a: "portal", tras: [0] },
        { ev: "bloquea", nodo: "portal", tras: [1] },
        { ev: "espera", nodo: "orq", espera: 800, tras: [1] },
        { ev: "envia", de: "orq", a: "grilla", espera: 1800 },
        { ev: "reanuda", nodo: "grilla", tras: [4] },
        { ev: "envia", de: "grilla", a: "bronce", tras: [4] },
      ],
    },
  ],
});
