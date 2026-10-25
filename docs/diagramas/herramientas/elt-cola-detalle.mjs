import { fileURLToPath } from "node:url";

import { construir, nota } from "./lib.mjs";

const DESTINO = fileURLToPath(new URL("..", import.meta.url));  // docs/diagramas/

await construir({
  archivo: "elt-cola-detalle",
  destino: DESTINO,
  pagina: "Cola y reglas del detalle",
  nodos: [
    { key: "vistos", shape: "cylinder", label: "Avisos vistos", color: "Almacén", x: 20, y: 250, w: 220, h: 110 },
    { key: "nuevo", shape: "rect", label: "1. Nuevo\nnunca visitado", color: "Servicio", x: 340, y: 20, w: 270, h: 90 },
    { key: "desaparecido", shape: "rect", label: "2. Desaparecido\nya no sale en la grilla", color: "Servicio", x: 340, y: 180, w: 270, h: 90 },
    { key: "tarjeta", shape: "rect", label: "3. Tarjeta cambiada\nsu tarjeta cambió", color: "Servicio", x: 340, y: 340, w: 270, h: 90 },
    { key: "rotacion", shape: "rect", label: "4. Rotación\ncada 1 a 14 días", color: "Servicio", x: 340, y: 500, w: 270, h: 90 },
    { key: "visita", shape: "rect", label: "Visita", color: "Config", x: 770, y: 255, w: 190, h: 100 },
    { key: "obs", shape: "cylinder", label: "Observación", color: "Almacén", x: 1120, y: 10, w: 250, h: 110 },
    { key: "proyecto", shape: "rect", label: "Proyecto: se excluye", color: "Externo", x: 1120, y: 180, w: 290, h: 90 },
    { key: "reintento", shape: "rect", label: "Reintenta en 12 h", color: "Cache", x: 1120, y: 350, w: 290, h: 90 },
    { key: "espera", shape: "rect", label: "429: espera 30 min", color: "Alerta", x: 1120, y: 520, w: 290, h: 90 },
    nota("n_excl", 10, 470, 280, 110, "Fuera de la cola:\nfinalizados, proyectos,\n5 fallos y otras comunas"),
    nota("n_rot", 330, 650, 400, 70, "Edad ≤ 14, 30, 60, 120 o más días:\nvuelve cada 2, 4, 7, 14 o 30 días"),
    nota("n_obs", 1420, 30, 250, 70, "Solo si el aviso cambió"),
    nota("n_esp", 1110, 650, 330, 70, "Pausas ×2 (hasta ×8); a la\nmitad cada 50 visitas buenas"),
  ],
  aristas: [
    { from: "vistos", to: "nuevo", label: "SQL", fromSide: "e", toSide: "w" },
    { from: "vistos", to: "desaparecido", fromSide: "e", toSide: "w" },
    { from: "vistos", to: "tarjeta", fromSide: "e", toSide: "w" },
    { from: "vistos", to: "rotacion", fromSide: "e", toSide: "w" },
    { from: "nuevo", to: "visita", fromSide: "e", toSide: "w" },
    { from: "desaparecido", to: "visita", fromSide: "e", toSide: "w" },
    { from: "tarjeta", to: "visita", fromSide: "e", toSide: "w" },
    { from: "rotacion", to: "visita", fromSide: "e", toSide: "w" },
    { from: "visita", to: "obs", label: "ok", fromSide: "e", toSide: "w" },
    { from: "visita", to: "proyecto", label: "proyecto", fromSide: "e", toSide: "w" },
    { from: "visita", to: "reintento", label: "error", fromSide: "e", toSide: "w" },
    { from: "visita", to: "espera", label: "429", fromSide: "e", toSide: "w" },
  ],
  eventos: [
    { ref: "excluye", name: "Se excluye", primitive: "OCCURRENCE", sentence: "{target}: no se vuelve a visitar" },
    { ref: "espera", name: "Espera", primitive: "OCCURRENCE", sentence: "{target} y baja el ritmo" },
  ],
  historias: [
    {
      nombre: "Un aviso nuevo se visita primero",
      pasos: [
        { ev: "envia", de: "vistos", a: "nuevo", espera: 0 },
        { ev: "envia", de: "nuevo", a: "visita", tras: [0] },
        { ev: "procesa", nodo: "visita", tras: [1] },
        { ev: "envia", de: "visita", a: "obs", tras: [1] },
      ],
    },
    {
      nombre: "Un aviso desaparecido resulta ser un proyecto",
      pasos: [
        { ev: "envia", de: "vistos", a: "desaparecido", espera: 0 },
        { ev: "envia", de: "desaparecido", a: "visita", tras: [0] },
        { ev: "procesa", nodo: "visita", tras: [1] },
        { ev: "envia", de: "visita", a: "proyecto", tras: [1] },
        { ev: "excluye", nodo: "proyecto", tras: [3] },
      ],
    },
    {
      nombre: "Revisita por rotación y un 429",
      pasos: [
        { ev: "envia", de: "vistos", a: "rotacion", espera: 0 },
        { ev: "envia", de: "rotacion", a: "visita", tras: [0] },
        { ev: "envia", de: "visita", a: "espera", espera: 800, tras: [1] },
        { ev: "espera", nodo: "espera", tras: [2] },
        { ev: "envia", de: "visita", a: "obs", espera: 2000 },
      ],
    },
  ],
});
