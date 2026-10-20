import { fileURLToPath } from "node:url";

import { construir, nota } from "./lib.mjs";

const DESTINO = fileURLToPath(new URL("..", import.meta.url));  // docs/diagramas/

await construir({
  archivo: "elt-gold",
  destino: DESTINO,
  pagina: "Gold: aptitud para entrenar",
  nodos: [
    { key: "silver", shape: "cylinder", label: "Silver", color: "Datos", x: 20, y: 250, w: 210, h: 110 },
    { key: "regla", shape: "diamond", label: "¿Apto?", color: "Alerta", x: 350, y: 225, w: 250, h: 150 },
    { key: "gold", shape: "cylinder", label: "Gold: aptos", color: "Datos", x: 720, y: 130, w: 240, h: 110 },
    { key: "modelo", shape: "rect", label: "Modelo (repo ML)", color: "IA", x: 1090, y: 140, w: 260, h: 90 },
    { key: "pred", shape: "cylinder", label: "gold.predicciones", color: "Éxito", x: 1090, y: 300, w: 260, h: 110 },
    { key: "noapto", shape: "rect", label: "No apto + motivo", color: "Externo", x: 720, y: 400, w: 240, h: 90 },
    { key: "scd2", shape: "cylinder", label: "SCD2: estado y precio", color: "Datos", x: 330, y: 500, w: 290, h: 110 },
    nota("n_apto", 690, -20, 290, 60, "Sin ningún motivo de exclusión"),
    nota("n_motivos", 1130, 480, 380, 170, "No apto si:\n• proyecto o sin detalle\n• finalizado hace más de 90 días\n• sin precio, superficie o coordenadas\n• banderas de anomalía"),
    nota("n_scd2", 640, 620, 330, 70, "Intervalos de vigencia de\nestado y de precio por aviso"),
  ],
  aristas: [
    { from: "silver", to: "regla", label: "evalúa" },
    { from: "regla", to: "gold", label: "sí" },
    { from: "regla", to: "noapto", label: "no" },
    { from: "gold", to: "modelo", label: "entrena" },
    { from: "modelo", to: "pred", label: "INSERT" },
    { from: "silver", to: "scd2", label: "historia", fromSide: "s", toSide: "w" },
  ],
  eventos: [
    { ref: "excluye", name: "Excluye", primitive: "OCCURRENCE", sentence: "{target}: se guarda el motivo" },
  ],
  historias: [
    {
      nombre: "Un aviso apto llega al modelo",
      pasos: [
        { ev: "envia", de: "silver", a: "regla", espera: 0 },
        { ev: "procesa", nodo: "regla", tras: [0] },
        { ev: "envia", de: "regla", a: "gold", tras: [0] },
        { ev: "envia", de: "gold", a: "modelo", espera: 600, tras: [2] },
        { ev: "envia", de: "modelo", a: "pred", tras: [3] },
        { ev: "procesa", nodo: "pred", tras: [4] },
      ],
    },
    {
      nombre: "Un aviso con superficie absurda queda fuera",
      pasos: [
        { ev: "envia", de: "silver", a: "regla", espera: 0 },
        { ev: "procesa", nodo: "regla", tras: [0] },
        { ev: "envia", de: "regla", a: "noapto", tras: [0] },
        { ev: "excluye", nodo: "noapto", tras: [2] },
      ],
    },
    {
      nombre: "Cada cambio queda con su vigencia",
      pasos: [
        { ev: "envia", de: "silver", a: "scd2", espera: 0 },
        { ev: "procesa", nodo: "scd2", tras: [0] },
      ],
    },
  ],
});
