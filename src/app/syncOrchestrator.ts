import { ApiError } from "./api";

// Deduplicação de sincronização por (client_id, provider, connection_id).
// Um primeiro clique inicia a chamada; qualquer chamada concorrente com a
// mesma identidade reutiliza a MESMA Promise em vez de disparar outro POST.
// Não faz retry automático — erro e sucesso propagam normalmente para quem
// chamou, e a entrada é liberada assim que a Promise original resolve.

type SyncIdentity = {
  clientId: string;
  provider: string;
  connectionId?: string | null;
};

const inFlight = new Map<string, Promise<unknown>>();

function buildKey({ clientId, provider, connectionId }: SyncIdentity): string {
  return `${String(clientId || "").trim()}|${String(provider || "").trim()}|${String(connectionId || "").trim() || "-"}`;
}

/**
 * Executa `task` no máximo uma vez por identidade (cliente + provedor +
 * conexão) enquanto houver uma execução em andamento. Chamadas subsequentes
 * com a mesma identidade recebem a Promise já em voo.
 */
export function runExclusiveSync<T>(identity: SyncIdentity, task: () => Promise<T>): Promise<T> {
  const key = buildKey(identity);
  const existing = inFlight.get(key);
  if (existing) {
    return existing as Promise<T>;
  }
  const promise = task().finally(() => {
    if (inFlight.get(key) === promise) {
      inFlight.delete(key);
    }
  });
  inFlight.set(key, promise);
  return promise;
}

export function isSyncInProgress(identity: SyncIdentity): boolean {
  return inFlight.has(buildKey(identity));
}

export function isSyncAlreadyRunningError(error: unknown): boolean {
  return error instanceof ApiError && error.code === "SYNC_ALREADY_RUNNING";
}

/** Mensagem amigável para erro de sync — nunca expõe o código técnico ao usuário. */
export function describeSyncError(error: unknown, fallback: string): string {
  if (isSyncAlreadyRunningError(error)) {
    return "A atualização já está em andamento.";
  }
  if (error instanceof ApiError && error.message) {
    return error.message;
  }
  return fallback;
}
