/**
 * Cores da Mugô para gráficos. Cada série/linha de um gráfico usa uma cor diferente, na ordem abaixo.
 * Base: o azul petróleo da marca (#004f6e) e as cores de apoio que a plataforma já usa.
 */
export const MUGO_PALETTE = [
  "#004f6e", // petróleo (cor da Mugô)
  "#c98a00", // mostarda
  "#26734d", // verde
  "#5b1f2a", // vinho
  "#4f8fa8", // azul claro
  "#c76b1e", // terracota
  "#17313d", // azul noite
  "#8a5a00", // ocre
] as const;

export const mugoColor = (index: number) => MUGO_PALETTE[((index % MUGO_PALETTE.length) + MUGO_PALETTE.length) % MUGO_PALETTE.length];

/** Sentimento tem cor fixa (não muda com a ordem). */
export const SENTIMENT_COLOR: Record<string, string> = {
  positivo: "#26734d", positiva: "#26734d", neutro: "#4f8fa8", neutra: "#4f8fa8",
  negativo: "#b22234", negativa: "#b22234", misto: "#c98a00", mista: "#c98a00",
};
