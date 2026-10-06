import { useCallback, useEffect, useRef, useState } from "react";
import { getClientIntegrations } from "../app/api";
import { getActiveClientId } from "../app/activeClient";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "./dashboard/cache";
import type { ClientIntegrationConnection } from "../app/types";
import { readOnce } from "./dashboard/readOnce";

type State = {
  connections: ClientIntegrationConnection[] | null;
  lastValidConnections: ClientIntegrationConnection[] | null;
  isLoading: boolean;
  isRefreshing: boolean;
  error: string | null;
  lastSuccessfulUpdate: string | null;
};

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function cacheKeyForClient(clientId: string): string {
  return buildDashboardCacheKey("client-integrations", { clientId });
}

/**
 * Leitura do contrato canônico de integrações (Fase 3). Nunca substitui
 * `lastValidConnections` por array vazio em loading/erro — só troca quando
 * uma resposta válida chega. Restaura do cache (memória + sessionStorage,
 * por client_id da empresa ativa) no primeiro render, para que troca de
 * rota/remount não zere os cards antes do refetch em segundo plano
 * terminar. Quem consome este hook deve renderizar `lastValidConnections`,
 * não `connections`.
 */
export default function useClientIntegrations(params: { enabled: boolean }) {
  const { enabled } = params;
  const clientId = getActiveClientId();
  const cacheKey = cacheKeyForClient(clientId);
  const cachedInitial = enabled ? readDashboardCache<ClientIntegrationConnection[]>(cacheKey) : null;

  const [state, setState] = useState<State>({
    connections: cachedInitial,
    lastValidConnections: cachedInitial,
    isLoading: false,
    isRefreshing: false,
    error: null,
    lastSuccessfulUpdate: null,
  });
  const abortRef = useRef<AbortController | null>(null);
  const requestRef = useRef(0);
  const lastValidRef = useRef<ClientIntegrationConnection[] | null>(cachedInitial);
  const clientIdRef = useRef(clientId);

  // Troca de empresa sem desmontagem (ex.: agency_admin alternando entre
  // Amalie e Roove) nunca pode deixar o card do tenant anterior visível
  // nem por um frame. useState só usa o valor inicial na primeira
  // montagem — então, ao detectar client_id diferente durante o render,
  // resetamos de forma síncrona (padrão React de "ajustar estado durante
  // o render") para o cache do NOVO cliente antes de qualquer commit,
  // e invalidamos qualquer resposta em voo do cliente anterior.
  if (clientIdRef.current !== clientId) {
    clientIdRef.current = clientId;
    abortRef.current?.abort();
    requestRef.current += 1;
    const nextCached = enabled ? readDashboardCache<ClientIntegrationConnection[]>(cacheKey) : null;
    lastValidRef.current = nextCached;
    setState({
      connections: nextCached,
      lastValidConnections: nextCached,
      isLoading: false,
      isRefreshing: false,
      error: null,
      lastSuccessfulUpdate: null,
    });
  }

  const refetch = useCallback(async (force = true) => {
    if (!enabled) return null;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const reqId = ++requestRef.current;
    const hasExisting = Boolean(lastValidRef.current);

    setState((prev) => ({ ...prev, isLoading: !hasExisting, isRefreshing: hasExisting, error: null }));

    try {
      const load = () => getClientIntegrations({ signal: force ? controller.signal : undefined });
      const response = force ? await load() : await readOnce(cacheKey, load);
      if (reqId !== requestRef.current) return null;
      const connections = Array.isArray(response.connections) ? response.connections : [];
      lastValidRef.current = connections;
      writeDashboardCache<ClientIntegrationConnection[]>(cacheKey, connections, 120_000);
      setState({
        connections,
        lastValidConnections: connections,
        isLoading: false,
        isRefreshing: false,
        error: null,
        lastSuccessfulUpdate: new Date().toISOString(),
      });
      return connections;
    } catch (error: unknown) {
      if (isAbortError(error) || reqId !== requestRef.current) return null;
      // Erro nunca apaga o último estado válido — só sinaliza o problema.
      setState((prev) => ({
        ...prev,
        isLoading: false,
        isRefreshing: false,
        error: errorMessage(error, "Não foi possível atualizar o status das integrações."),
      }));
      return null;
    }
  }, [enabled, cacheKey]);

  useEffect(() => {
    if (!enabled) return;
    // Restauração do cache já aconteceu no useState inicial acima; aqui só
    // disparamos o refetch em segundo plano (isRefreshing, não isLoading,
    // quando já havia algo em cache).
    if (readDashboardCache<ClientIntegrationConnection[]>(cacheKey)) return;
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void refetch(false); });
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, [cacheKey, enabled, refetch]);

  return { ...state, refetch };
}
