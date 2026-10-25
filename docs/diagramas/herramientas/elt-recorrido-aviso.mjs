import { fileURLToPath } from "node:url";

import { construir, nota } from "./lib.mjs";

const DESTINO = fileURLToPath(new URL("..", import.meta.url));  // docs/diagramas/

// El recorrido de un solo aviso: de la página del sitio a Landing, Bronce, Silver y Gold, y de ahí al modelo y al mapa.
// Sin el nombre del portal: es la versión pensada para compartir.
await construir({
  archivo: "elt-recorrido-aviso",
  destino: DESTINO,
  pagina: "Recorrido de un aviso",
  nodos: [
    { key: "sitio", shape: "rect", label: "Sitio de avisos", color: "Externo", x: 20, y: 215, w: 230, h: 90 },
    { key: "scraper", shape: "rect", label: "Scraper de detalle", color: "Servicio", x: 340, y: 215, w: 230, h: 90 },
    { key: "landing", shape: "cylinder", label: "Landing (staging)", color: "Cache", x: 340, y: 440, w: 230, h: 100 },
    { key: "bronce", shape: "cylinder", label: "Bronce", color: "Almacén", x: 700, y: 205, w: 210, h: 110 },
    { key: "silver", shape: "cylinder", label: "Silver", color: "Datos", x: 1040, y: 205, w: 210, h: 110 },
    { key: "mindicador", shape: "rect", label: "UF y dólar", color: "Externo", x: 910, y: 440, w: 190, h: 80 },
    { key: "igvust", shape: "rect", label: "IGVUST", color: "Externo", x: 1130, y: 440, w: 150, h: 80 },
    { key: "gold", shape: "cylinder", label: "Gold", color: "Datos", x: 1380, y: 205, w: 210, h: 110 },
    { key: "modelo", shape: "rect", label: "Modelo de ML", color: "IA", x: 1380, y: 400, w: 230, h: 90 },
    { key: "pred", shape: "cylinder", label: "gold.predicciones", color: "Éxito", x: 1380, y: 560, w: 230, h: 100 },
    { key: "mapa", shape: "rect", label: "Mapa web", color: "Éxito", x: 1040, y: 575, w: 230, h: 90 },
    nota("n_sitio", 0, 90, 230, 66, "Un aviso nuevo\nen el sitio"),
    nota("n_scraper", 320, 90, 290, 66, "Lo visita con pausas\ny extrae sus campos"),
    nota("n_landing", 310, 570, 290, 66, "HTML crudo, comprimido,\nlocal y fuera de git"),
    nota("n_bronce", 680, 80, 250, 66, "Fila nueva solo si\ncambió (hash)"),
    nota("n_silver", 1020, 80, 250, 66, "Estado, UF a pesos\ny banderas de calidad"),
    nota("n_gold", 1360, 80, 250, 66, "Antigüedad completa\ny motivos de exclusión"),
    nota("n_mapa", 1010, 690, 290, 66, "Lee Gold y las\npredicciones"),
  ],
  aristas: [
    { from: "scraper", to: "sitio", label: "visita" },
    { from: "scraper", to: "landing", label: "HTML" },
    { from: "scraper", to: "bronce", label: "campos" },
    { from: "bronce", to: "silver", label: "tipa" },
    { from: "mindicador", to: "silver", label: "UF, dólar" },
    { from: "igvust", to: "silver", label: "UV" },
    { from: "silver", to: "gold", label: "aptos" },
    { from: "gold", to: "modelo", label: "datos" },
    { from: "modelo", to: "pred", label: "INSERT" },
    { from: "pred", to: "mapa", label: "etiqueta" },
  ],
  historias: [
    {
      nombre: "Un aviso, de la página al mapa",
      pasos: [
        { ev: "envia", de: "scraper", a: "sitio", espera: 0 },
        { ev: "envia", de: "scraper", a: "landing", tras: [0] },
        { ev: "envia", de: "scraper", a: "bronce", tras: [0] },
        { ev: "envia", de: "bronce", a: "silver", tras: [2] },
        { ev: "envia", de: "mindicador", a: "silver", tras: [2] },
        { ev: "envia", de: "igvust", a: "silver", tras: [2] },
        { ev: "procesa", nodo: "silver", tras: [3, 4, 5] },
        { ev: "envia", de: "silver", a: "gold", tras: [3, 4, 5] },
        { ev: "procesa", nodo: "gold", tras: [7] },
        { ev: "envia", de: "gold", a: "modelo", tras: [7] },
        { ev: "envia", de: "modelo", a: "pred", tras: [9] },
        { ev: "envia", de: "pred", a: "mapa", tras: [10] },
        { ev: "procesa", nodo: "mapa", tras: [11] },
      ],
    },
  ],
});
