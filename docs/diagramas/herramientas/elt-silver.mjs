import { fileURLToPath } from "node:url";

import { construir, nota } from "./lib.mjs";

const DESTINO = fileURLToPath(new URL("..", import.meta.url));  // docs/diagramas/

await construir({
  archivo: "elt-silver",
  destino: DESTINO,
  pagina: "Silver: limpieza y banderas",
  nodos: [
    { key: "bronce", shape: "cylinder", label: "Bronce", color: "Almacén", x: 20, y: 250, w: 210, h: 110 },
    { key: "mind", shape: "rect", label: "UF y dólar", color: "Externo", x: 350, y: 60, w: 240, h: 80 },
    { key: "tipado", shape: "rect", label: "Tipa y pasa a CLP", color: "Servicio", x: 340, y: 255, w: 260, h: 90 },
    { key: "estado", shape: "rect", label: "Estado del aviso", color: "Servicio", x: 700, y: 255, w: 250, h: 90 },
    { key: "banderas", shape: "rect", label: "Banderas de calidad", color: "Alerta", x: 1060, y: 255, w: 270, h: 90 },
    { key: "atipico", shape: "rect", label: "Precio por m² atípico", color: "Alerta", x: 1060, y: 470, w: 290, h: 90 },
    { key: "igvust", shape: "rect", label: "IGVUST (UV)", color: "Externo", x: 1460, y: 60, w: 200, h: 80 },
    { key: "silver", shape: "cylinder", label: "Silver", color: "Datos", x: 1450, y: 245, w: 210, h: 110 },
    nota("n_tipado", 330, 400, 290, 70, "UF y dólar del día de la\nvisita (hasta 5 días atrás)"),
    nota("n_estado", 690, 400, 280, 90, "Sin texto: activo\n«finaliz…»: finalizado\n«pausad…»: pausado"),
    nota("n_banderas", 960, 50, 320, 110, "Superficie < 12 o > 500 m²\nPrecio < 100 mil o > 8 M\nConteos imposibles\nSin coordenadas o fuera de la RM"),
    nota("n_atipico", 1030, 590, 340, 70, "z robusto del costo por m²\n> 5 respecto de su comuna"),
  ],
  aristas: [
    { from: "bronce", to: "tipado", label: "datos" },
    { from: "mind", to: "tipado", label: "UF, dólar" },
    { from: "tipado", to: "estado", label: "tipado" },
    { from: "estado", to: "banderas", label: "banderas" },
    { from: "banderas", to: "silver", label: "avisos" },
    { from: "atipico", to: "silver", label: "segunda pasada", fromSide: "e", toSide: "s" },
    { from: "igvust", to: "silver", label: "UV" },
  ],
  eventos: [
    { ref: "marca", name: "Marca", primitive: "OCCURRENCE", sentence: "{target} marca una anomalía" },
  ],
  historias: [
    {
      nombre: "Un aviso normal, de Bronce a Silver",
      pasos: [
        { ev: "envia", de: "bronce", a: "tipado", espera: 0 },
        { ev: "envia", de: "mind", a: "tipado", espera: 100 },
        { ev: "procesa", nodo: "tipado", tras: [0, 1] },
        { ev: "envia", de: "tipado", a: "estado", tras: [0, 1] },
        { ev: "procesa", nodo: "estado", tras: [3] },
        { ev: "envia", de: "estado", a: "banderas", tras: [3] },
        { ev: "envia", de: "banderas", a: "silver", espera: 600, tras: [5] },
        { ev: "envia", de: "igvust", a: "silver", tras: [5] },
        { ev: "envia", de: "atipico", a: "silver", espera: 900, tras: [6] },
      ],
    },
    {
      nombre: "Un aviso con precio por m² absurdo",
      pasos: [
        { ev: "envia", de: "bronce", a: "tipado", espera: 0 },
        { ev: "envia", de: "tipado", a: "estado", tras: [0] },
        { ev: "envia", de: "estado", a: "banderas", tras: [1] },
        { ev: "envia", de: "banderas", a: "silver", espera: 600, tras: [2] },
        { ev: "marca", nodo: "atipico", espera: 900, tras: [3] },
        { ev: "envia", de: "atipico", a: "silver", tras: [3] },
      ],
    },
  ],
});
