import { fileURLToPath } from "node:url";

import { construir, nota } from "./lib.mjs";

const DESTINO = fileURLToPath(new URL("..", import.meta.url));  // docs/diagramas/

await construir({
  archivo: "elt-orquestador",
  destino: DESTINO,
  pagina: "Orquestador del scraping",
  nodos: [
    { key: "orq", shape: "rect", label: "Orquestador", color: "Config", x: 40, y: 330, w: 220, h: 90 },
    { key: "detalle", shape: "rect", label: "Detalle (tandas de 400)", color: "Servicio", x: 420, y: 150, w: 240, h: 80 },
    { key: "grilla", shape: "rect", label: "Grilla (cada 6 h)", color: "Servicio", x: 420, y: 520, w: 240, h: 80 },
    { key: "portal", shape: "rect", label: "Portal Inmobiliario", color: "Externo", x: 880, y: 335, w: 220, h: 80 },
    { key: "espera", shape: "rect", label: "Espera 30 min y baja el ritmo", color: "Alerta", x: 850, y: 30, w: 300, h: 80 },
    { key: "bronce", shape: "cylinder", label: "Bronce", color: "Almacén", x: 1330, y: 320, w: 220, h: 110 },
    nota("n_orq", 20, 170, 250, 98, "Alterna tandas de detalle y la\ngrilla. La grilla entra cada 6 h aunque\nla cola sea larga. Sin nada que\nvisitar, espera hasta 30 min."),
    nota("n_detalle", 400, 20, 400, 98, "Cola: nuevo, desaparecido, tarjeta cambiada\ny rotación por antigüedad (1, 2, 4, 7 o 14 días).\nPresupuesto: 6.000 visitas por 24 h.\nPausas de 3 a 6 s."),
    nota("n_espera", 1240, 20, 440, 118, "429: espera 30 min, duplica las pausas (hasta ×8)\ny las baja a la mitad cada 50 visitas buenas.\nSi 3 bloqueos seguidos no avanzan, aborta y el\norquestador espera 30, 60 o 120 min."),
    nota("n_grilla", 400, 640, 360, 98, "12 comunas. Si la bloquean, reanuda solo las\nque faltaban. Una grilla incompleta no marca\navisos como desaparecidos en las comunas\nque no cubrió."),
  ],
  aristas: [
    { from: "orq", to: "detalle", label: "tanda" },
    { from: "orq", to: "grilla", label: "si toca" },
    { from: "detalle", to: "portal", label: "visita aviso" },
    { from: "grilla", to: "portal", label: "páginas" },
    { from: "detalle", to: "bronce", label: "observación", fromSide: "e", toSide: "n" },
    { from: "grilla", to: "bronce", label: "tarjetas", fromSide: "e", toSide: "s" },
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
