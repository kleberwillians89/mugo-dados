/** Instagram no feed: a proporção do 1º slide vale para todos, entre 4:5 (em pé) e 1,91:1 (deitado). */
export function feedRatio(width: number, height: number): number {
  if (!width || !height) return 4 / 5;
  return Math.min(1.91, Math.max(4 / 5, width / height));
}

/**
 * Proporção da prévia de aprovação. Stories e Reels são sempre 9:16 (tela cheia), sem o limite do feed.
 * Feed, carrossel e vídeo seguem a arte (1º slide), dentro do que o Instagram mostra no feed: 4:5 a 1,91:1.
 */
export function approvalRatio(format: string | null | undefined, width?: number, height?: number): number {
  if (format === "stories" || format === "reels") return 9 / 16;
  return width && height ? feedRatio(width, height) : 4 / 5;
}
