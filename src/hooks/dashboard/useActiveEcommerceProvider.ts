import { useCallback, useEffect, useRef, useState } from "react";
import { readOnce } from "./readOnce";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "./cache";
import { listGenericConnections, type GenericConnection } from "../../app/api";
import type { ClientIntegrationConnection } from "../../app/types";

/**
 * Conexões do tenant no formato que a página de e-commerce consome.
 *
 * A fonte é `/api/connections`, que qualquer MEMBRO da empresa lê — não o
 * contrato canônico de `/api/clients/{id}/integrations`, que é administrativo
 * (expõe ad_account_id, business_id, property_id) e responde 403 para viewer
 * por decisão de produto. Resolver qual loja está ativa é leitura de dados,
 * não configuração de integração: um viewer precisa disso para ver o próprio
 * faturamento.
 *
 * Só os campos que a página usa são mapeados. O último sucesso vem da
 * metadata persistida; `last_sync_at` mantém compatibilidade com conexões antigas.
 */
function toEcommerceConnection(row: GenericConnection): ClientIntegrationConnection {
  return {
    provider: String(row.provider || ""),
    connection_id: String(row.id || ""),
    status: String(row.status || ""),
    authorization_status: "valid",
    // Este contrato não carrega status de sync; a página não o usa.
    sync_status: null,
    account: { id: row.account_id ?? null, name: row.account_name ?? null, domain: null },
    assets: {},
    last_sync_at: row.last_sync_at ?? null,
    last_successful_sync_at: String(row.metadata?.last_success_at || "") || null,
    last_error: row.last_error ?? null,
    updated_at: null,
  };
}

type State = {
  clientId: string;
  loading: boolean;
  error: string | null;
  connections: ClientIntegrationConnection[] | null;
};

type LoadOptions = {
  /** Volta para "carregando" antes de ler (botão Tentar novamente). */
  showLoading?: boolean;
  /** Em falha, mantém a tela atual (recarga após "Sincronizar agora"). */
  keepOnFailure?: boolean;
};

/**
 * Lê as conexões canônicas da empresa ativa (mesma fonte do card de
 * Integrações). Respostas de outro tenant ou de uma requisição anterior são
 * descartadas, e nada do tenant anterior é exposto quando a empresa muda.
 */
export default function useActiveEcommerceProvider(activeClientId: string) {
  const cacheKey = buildDashboardCacheKey("commerce-connections", { clientId: activeClientId });
  const cached = readDashboardCache<ClientIntegrationConnection[]>(cacheKey);
  const [state, setState] = useState<State>({ clientId: activeClientId, loading: !cached, error: null, connections: cached });
  const generation = useRef(0);

  // Só altera estado depois do await: seguro para ser chamado por efeito.
  const fetchConnections = useCallback(async (requestId: number, requestedClientId: string, keepOnFailure: boolean) => {
    try {
      const response = await readOnce(buildDashboardCacheKey("commerce-connections", { clientId: requestedClientId }), () => listGenericConnections());
      if (requestId !== generation.current) return;
      if (String(response?.client_id || "") !== requestedClientId) {
        if (keepOnFailure) return;
        setState({ clientId: requestedClientId, loading: false, error: "A empresa ativa mudou durante a leitura. Tente novamente.", connections: null });
        return;
      }
      writeDashboardCache(buildDashboardCacheKey("commerce-connections", { clientId: requestedClientId }), (response.connections || []).map(toEcommerceConnection), 180_000);
      setState({
        clientId: requestedClientId,
        loading: false,
        error: null,
        connections: (response.connections || []).map(toEcommerceConnection),
      });
    } catch (cause) {
      if (requestId !== generation.current || keepOnFailure) return;
      setState({
        clientId: requestedClientId,
        loading: false,
        error: cause instanceof Error && cause.message ? cause.message : "Não foi possível verificar as integrações de e-commerce.",
        connections: null,
      });
    }
  }, []);

  const load = useCallback(async (options: LoadOptions = {}) => {
    if (!activeClientId) return;
    const requestId = ++generation.current;
    if (options.showLoading) setState({ clientId: activeClientId, loading: true, error: null, connections: null });
    await fetchConnections(requestId, activeClientId, Boolean(options.keepOnFailure));
  }, [activeClientId, fetchConnections]);

  useEffect(() => {
    if (!activeClientId) return undefined;
    const requestId = ++generation.current;
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void fetchConnections(requestId, activeClientId, false); });
    return () => {
      cancelled = true;
      generation.current += 1;
    };
  }, [activeClientId, fetchConnections]);

  if (!activeClientId) {
    return { loading: false, error: null, connections: [], reload: load, refresh: load };
  }
  const current = state.clientId === activeClientId;
  return {
    loading: !cached && (!current || state.loading),
    error: current ? state.error : null,
    connections: (current ? state.connections : null) || cached,
    reload: () => load({ showLoading: true }),
    refresh: () => load({ keepOnFailure: true }),
  };
}
