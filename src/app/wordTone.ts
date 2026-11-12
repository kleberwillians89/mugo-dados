import type { CommentSentiment, TopWord } from "./types";

/** Nuvem de palavras: nomes dos tons e a dica com a divisão dos comentários de cada palavra. */
export const TONES: CommentSentiment[] = ["positivo", "neutro", "misto", "negativo"];
export const TONE_NAME: Record<CommentSentiment, string> = { positivo: "Positivo", neutro: "Neutro", misto: "Misto", negativo: "Negativo" };
const TONE_PLURAL: Record<CommentSentiment, string> = { positivo: "positivos", neutro: "neutros", misto: "mistos", negativo: "negativos" };

/** "elogio: 12 menções · 8 positivos, 1 negativo" — divisão dos comentários em que a palavra aparece. */
export function wordTitle(w: TopWord): string {
  const parts = TONES.filter((t) => Number(w.sentiment?.[t] || 0) > 0).map((t) => {
    const n = Number(w.sentiment?.[t] || 0);
    return `${n} ${n === 1 ? TONE_NAME[t].toLowerCase() : TONE_PLURAL[t]}`;
  });
  const pending = Number(w.sentiment?.sem_analise || 0);
  if (pending) parts.push(`${pending} sem análise`);
  return `${w.word}: ${w.count} ${w.count === 1 ? "menção" : "menções"}${parts.length ? ` · ${parts.join(", ")}` : ""}`;
}
