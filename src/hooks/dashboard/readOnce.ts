const pending = new Map<string, Promise<unknown>>();

/** Compartilha só leituras idênticas em voo; não cria cache de erros/dados. */
export async function readOnce<T>(key: string, load: () => Promise<T>): Promise<T> {
  const existing = pending.get(key);
  if (existing) return existing as Promise<T>;
  const request = load();
  pending.set(key, request);
  try { return await request; }
  finally { if (pending.get(key) === request) pending.delete(key); }
}
