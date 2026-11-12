/**
 * Cores da Mugô para gráficos. Cada série/linha de um gráfico usa uma cor diferente, na ordem abaixo.
 * Base: a paleta oficial da Mugô (azul, dourado, vermelho, grafite, areia e off-white #f4f4f4).
 */
export const MUGO_PALETTE = [
  "#1e3f5a", // azul Mugô
  "#c09a45", // dourado Mugô
  "#a33038", // vermelho Mugô
  "#5d6770", // grafite Mugô
  "#c4b49a", // areia Mugô
  "#4f7894", // azul claro (apoio)
  "#8a6d2e", // ouro velho (apoio)
  "#2b2f33", // grafite escuro (apoio)
] as const;

export const mugoColor = (index: number) => MUGO_PALETTE[((index % MUGO_PALETTE.length) + MUGO_PALETTE.length) % MUGO_PALETTE.length];

/** Sentimento tem cor fixa (não muda com a ordem). */
export const SENTIMENT_COLOR: Record<string, string> = {
  positivo: "#26734d", positiva: "#26734d", neutro: "#4f8fa8", neutra: "#4f8fa8",
  negativo: "#a33038", negativa: "#a33038", misto: "#c09a45", mista: "#c09a45",
};
