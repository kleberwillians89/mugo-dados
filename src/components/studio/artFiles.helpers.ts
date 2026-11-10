/** Mover um item da lista (ordem = slides do carrossel). */
export function moveArt(list: string[], index: number, delta: number): string[] {
  const to = index + delta;
  if (to < 0 || to >= list.length) return list;
  const next = [...list];
  [next[index], next[to]] = [next[to], next[index]];
  return next;
}
