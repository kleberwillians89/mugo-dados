/** Instagram no feed: a proporção do 1º slide vale para todos, entre 4:5 (em pé) e 1,91:1 (deitado). */
export function feedRatio(width: number, height: number): number {
  if (!width || !height) return 4 / 5;
  return Math.min(1.91, Math.max(4 / 5, width / height));
}
