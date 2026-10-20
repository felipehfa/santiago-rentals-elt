import { fileURLToPath } from "node:url";

import { construir, nota } from "./lib.mjs";

const DESTINO = fileURLToPath(new URL("..", import.meta.url));  // docs/diagramas/

await construir({
  archivo: "elt-grilla",
  destino: DESTINO,
  pagina: "Flujo de la grilla",
  nodos: [
    { key: "comuna", shape: "rect", label: "Cada comuna", color: "Config", x: 20, y: 160, w: 230, h: 90 },
    { key: "pagina1", shape: "rect", label: "Total declarado", color: "Servicio", x: 340, y: 160, w: 250, h: 90 },
    { key: "gate", shape: "diamond", label: "¿Más de 1.800?", color: "Alerta", x: 680, y: 135, w: 260, h: 140 },
    { key: "rangos", shape: "rect", label: "Parte por precio", color: "Servicio", x: 1040, y: 20, w: 250, h: 90 },
    { key: "paginas", shape: "rect", label: "Recorre páginas", color: "Servicio", x: 1040, y: 250, w: 250, h: 90 },
    { key: "bronce", shape: "cylinder", label: "Bronce", color: "Almacén", x: 1400, y: 240, w: 210, h: 110 },
    { key: "cobertura", shape: "rect", label: "Cobertura", color: "Info", x: 1400, y: 470, w: 210, h: 90 },
    { key: "bloqueo", shape: "rect", label: "Bloqueo: aborta", color: "Alerta", x: 1040, y: 470, w: 250, h: 90 },
    nota("n_pagina1", 320, 30, 270, 70, "El sitio corta cada búsqueda\nen 2.016 resultados"),
    nota("n_rangos", 1320, 20, 270, 70, "Escalera de rangos; divide\nlos grandes a la mitad"),
    nota("n_bronce", 1400, 130, 210, 60, "Solo si la tarjeta cambió"),
    nota("n_cobertura", 1380, 590, 270, 70, "Completa si faltan menos\nde max(10, 1 %)"),
    nota("n_bloqueo", 1000, 590, 290, 70, "429, 403 o página 1 vacía\n3 veces: nunca es éxito"),
  ],
  aristas: [
    { from: "comuna", to: "pagina1", label: "pide" },
    { from: "pagina1", to: "gate", label: "total" },
    { from: "gate", to: "rangos", label: "sí" },
    { from: "gate", to: "paginas", label: "no" },
    { from: "rangos", to: "paginas", label: "cada rango" },
    { from: "paginas", to: "bronce", label: "tarjetas" },
    { from: "bronce", to: "cobertura", label: "cierra" },
    { from: "paginas", to: "bloqueo", label: "bloqueo" },
  ],
  eventos: [
    { ref: "bloquea", name: "Bloquea", primitive: "OCCURRENCE", sentence: "{target}: el sitio bloquea" },
    { ref: "completa", name: "Completa", primitive: "OCCURRENCE", sentence: "{target} queda completa" },
  ],
  historias: [
    {
      nombre: "Una comuna chica: sin partir",
      pasos: [
        { ev: "envia", de: "comuna", a: "pagina1", espera: 0 },
        { ev: "envia", de: "pagina1", a: "gate", tras: [0] },
        { ev: "procesa", nodo: "gate", tras: [1] },
        { ev: "envia", de: "gate", a: "paginas", tras: [1] },
        { ev: "envia", de: "paginas", a: "bronce", espera: 700, tras: [3] },
        { ev: "envia", de: "bronce", a: "cobertura", tras: [4] },
        { ev: "completa", nodo: "cobertura", tras: [5] },
      ],
    },
    {
      nombre: "Santiago: más de 1.800, se parte por precio",
      pasos: [
        { ev: "envia", de: "comuna", a: "pagina1", espera: 0 },
        { ev: "envia", de: "pagina1", a: "gate", tras: [0] },
        { ev: "envia", de: "gate", a: "rangos", tras: [1] },
        { ev: "procesa", nodo: "rangos", tras: [2] },
        { ev: "envia", de: "rangos", a: "paginas", espera: 700, tras: [2] },
        { ev: "envia", de: "paginas", a: "bronce", espera: 700, tras: [4] },
        { ev: "envia", de: "bronce", a: "cobertura", tras: [5] },
        { ev: "completa", nodo: "cobertura", tras: [6] },
      ],
    },
    {
      nombre: "El sitio bloquea la búsqueda",
      pasos: [
        { ev: "envia", de: "comuna", a: "pagina1", espera: 0 },
        { ev: "envia", de: "pagina1", a: "gate", tras: [0] },
        { ev: "envia", de: "gate", a: "paginas", tras: [1] },
        { ev: "envia", de: "paginas", a: "bloqueo", espera: 800, tras: [2] },
        { ev: "bloquea", nodo: "bloqueo", tras: [3] },
      ],
    },
  ],
});
