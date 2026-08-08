import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getGa4Report, listGenericConnections } from "../../app/api";
import { getSelectedConnectionId, setSelectedConnectionId } from "../../app/connectionState";
import type { Ga4ReportResponse } from "../../app/types";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";
import {
  buildDashboardCacheKey,
  readDashboardCache,
  writeDashboardCache,
} from "./cache";

const ACTIVE_CONNECTION_STATUSES = new Set(["connected", "active", "ok"]);

// A leitura GA4 exige connection_id explícito no backend (nunca escolhe
// sozinho entre várias contas). Quando o ponteiro local (localStorage)
// ainda não existe — ex.: conexão feita em outra sessão/navegador — mas a
// empresa tem exatamente UMA conexão GA4 ativa, persistimos esse único
// candidato como selecionado antes de ler. Nunca escolhe entre 2+ conexões:
// aí a ambiguidade real precisa continuar exigindo seleção explícita.
async function ensureGa4ConnectionSelected(clientId: string): Promise<void> {
  if (getSelectedConnectionId(clientId, "ga4")) return;
  try {
    const { connections } = await listGenericConnections();
    const candidates = (connections || []).filter(
      (connection) =>
        connection.client_id === clientId &&
        connection.provider === "ga4" &&
        !connection.disconnected_at &&
        ACTIVE_CONNECTION_STATUSES.has(String(connection.status || "").trim().toLowerCase())
    );
    if (candidates.length === 1) {
      setSelectedConnectionId(clientId, "ga4", candidates[0].id);
    }
  } catch {
    // Sem lista de conexões disponível: segue sem connection_id — o
    // backend responde 409 explicitamente, nunca um fallback silencioso.
  }
}

type Params = {
  isAuthenticated: boolean;
  activeClientId: string;
  period?: DashboardPeriod | null;
};

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function periodDays(start: string, end: string): number {
  const startDate = new Date(`${String(start || "").trim()}T00:00:00`);
  const endDate = new Date(`${String(end || "").trim()}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return 30;
  const diff = endDate.getTime() - startDate.getTime();
  if (!Number.isFinite(diff) || diff < 0) return 30;
  return Math.max(1, Math.floor(diff / 86_400_000) + 1);
}

export default function useDashboardGa4({
  isAuthenticated,
  activeClientId,
  period,
}: Params) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
  const cacheKey = useMemo(
    () =>
      buildDashboardCacheKey("ga4", {
        clientId: activeClientId,
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, safePeriod.end, safePeriod.start]
  );
  const safeDays = useMemo(
    () => periodDays(safePeriod.start, safePeriod.end),
    [safePeriod.end, safePeriod.start]
  );
  const cachedInitial = useMemo(
    () => (activeClientId ? readDashboardCache<Ga4ReportResponse>(cacheKey) : null),
    [activeClientId, cacheKey]
  );

  const [ga4Report, setGa4Report] = useState<Ga4ReportResponse | null>(cachedInitial);
  const [loadingGa4, setLoadingGa4] = useState(false);
  const [refreshingGa4, setRefreshingGa4] = useState(false);
  const [ga4Error, setGa4Error] = useState<string | null>(null);
  const [ga4UpdatedAt, setGa4UpdatedAt] = useState<string | null>(null);
  const requestRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const dataRef = useRef<Ga4ReportResponse | null>(cachedInitial);
  const cacheKeyRef = useRef(cacheKey);

  useEffect(() => {
    dataRef.current = ga4Report;
  }, [ga4Report]);

  // Troca de empresa (cacheKey inclui client_id) nunca pode deixar o
  // relatório GA4 do tenant anterior visível — nem por um frame. Reset
  // síncrono durante o render (não em useEffect, que só roda após o
  // commit), inclusive quando o novo tenant ainda não tem nada em cache
  // (antes, esse caso não limpava nada e mantinha o relatório antigo).
  if (cacheKeyRef.current !== cacheKey) {
    cacheKeyRef.current = cacheKey;
    abortRef.current?.abort();
    requestRef.current += 1;
    dataRef.current = cachedInitial;
    setGa4Report(cachedInitial);
    setGa4Error(null);
    setGa4UpdatedAt(null);
  }

  const reloadGa4 = useCallback(
    async (options?: { force?: boolean }) => {
      if (!isAuthenticated || !activeClientId) return null;

      const force = !!options?.force;
      const cached = !force ? readDashboardCache<Ga4ReportResponse>(cacheKey) : null;
      if (cached) {
        setGa4Report(cached);
        dataRef.current = cached;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const reqId = ++requestRef.current;
      const hasExistingData = Boolean(dataRef.current || cached);

      setLoadingGa4(!hasExistingData);
      setRefreshingGa4(hasExistingData);
      setGa4Error(null);

      try {
        await ensureGa4ConnectionSelected(activeClientId);
        const response = await getGa4Report({
          start: safePeriod.start,
          end: safePeriod.end,
          days: safeDays,
        }, {
          clientId: activeClientId,
          signal: controller.signal,
        });
        if (reqId !== requestRef.current) return null;
        setGa4Report(response);
        dataRef.current = response;
        setGa4UpdatedAt(new Date().toISOString());
        writeDashboardCache<Ga4ReportResponse>(cacheKey, response, 180_000);
        return response;
      } catch (error: unknown) {
        if (isAbortError(error) || reqId !== requestRef.current) return null;
        setGa4Error(errorMessage(error, "Erro ao carregar dados de GA4"));
        return null;
      } finally {
        if (reqId === requestRef.current) {
          setLoadingGa4(false);
          setRefreshingGa4(false);
        }
      }
    },
    [activeClientId, cacheKey, isAuthenticated, safeDays, safePeriod.end, safePeriod.start]
  );

  useEffect(() => {
    if (!isAuthenticated || !activeClientId) return;
    void reloadGa4();
    return () => {
      abortRef.current?.abort();
    };
  }, [activeClientId, isAuthenticated, reloadGa4]);

  // Leitura nunca dispara sincronização automaticamente. Dado "stale" é
  // apenas exibido como tal; atualizar é ação explícita do usuário,
  // orquestrada por src/app/syncOrchestrator.ts.

  return {
    ga4Report,
    loadingGa4,
    refreshingGa4,
    ga4Error,
    ga4UpdatedAt,
    reloadGa4,
  };
}
