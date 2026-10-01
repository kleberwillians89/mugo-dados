import { useCallback, useEffect, useRef, useState } from "react";
import { getClientIntegrations } from "../../app/api";
import type { ClientIntegrationConnection } from "../../app/types";

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
  const [state, setState] = useState<State>({ clientId: activeClientId, loading: true, error: null, connections: null });
  const generation = useRef(0);

  // Só altera estado depois do await: seguro para ser chamado por efeito.
  const fetchConnections = useCallback(async (requestId: number, requestedClientId: string, keepOnFailure: boolean) => {
    try {
      const response = await getClientIntegrations();
      if (requestId !== generation.current) return;
      if (String(response?.client_id || "") !== requestedClientId) {
        if (keepOnFailure) return;
        setState({ clientId: requestedClientId, loading: false, error: "A empresa ativa mudou durante a leitura. Tente novamente.", connections: null });
        return;
      }
      setState({ clientId: requestedClientId, loading: false, error: null, connections: response.connections || [] });
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
    void fetchConnections(requestId, activeClientId, false);
    return () => {
      generation.current += 1;
    };
  }, [activeClientId, fetchConnections]);

  if (!activeClientId) {
    return { loading: false, error: null, connections: [], reload: load, refresh: load };
  }
  const current = state.clientId === activeClientId;
  return {
    loading: !current || state.loading,
    error: current ? state.error : null,
    connections: current ? state.connections : null,
    reload: () => load({ showLoading: true }),
    refresh: () => load({ keepOnFailure: true }),
  };
}
