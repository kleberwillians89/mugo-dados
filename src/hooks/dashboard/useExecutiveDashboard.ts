import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getExecutiveDashboard } from "../../app/api";
import type { ExecutiveDashboardResponse } from "../../app/types";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "./cache";

type Params = {
  isAuthenticated: boolean;
  activeClientId: string;
  enabled?: boolean;
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

// Operação real (Shopify líquido + ROAS combinado transparente): leitura
// pura de dados já persistidos. Nunca dispara sincronização — a atualização
// só acontece pelo botão "Atualizar" explícito, que sincroniza a origem e
// então chama reloadExecutive({ force: true }).
export default function useExecutiveDashboard({
  isAuthenticated,
  activeClientId,
  enabled = true,
  period,
}: Params) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
  const cacheKey = useMemo(
    () =>
      buildDashboardCacheKey("executive", {
        clientId: activeClientId,
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, safePeriod.end, safePeriod.start]
  );
  const cachedInitial = useMemo(
    () => readDashboardCache<ExecutiveDashboardResponse>(cacheKey),
    [cacheKey]
  );

  const [executiveData, setExecutiveData] = useState<ExecutiveDashboardResponse | null>(cachedInitial);
  const [loadingExecutive, setLoadingExecutive] = useState(false);
  const [executiveError, setExecutiveError] = useState<string | null>(null);
  const requestRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const dataRef = useRef<ExecutiveDashboardResponse | null>(cachedInitial);
  const cacheKeyRef = useRef(cacheKey);

  useEffect(() => {
    dataRef.current = executiveData;
  }, [executiveData]);

  if (cacheKeyRef.current !== cacheKey) {
    cacheKeyRef.current = cacheKey;
    abortRef.current?.abort();
    requestRef.current += 1;
    dataRef.current = cachedInitial;
    setExecutiveData(cachedInitial);
    setExecutiveError(null);
  }

  const reloadExecutive = useCallback(
    async (options?: { force?: boolean }) => {
      if (!isAuthenticated || !activeClientId) return null;
      const force = !!options?.force;
      if (!enabled && !force) return dataRef.current;

      const cached = !force ? readDashboardCache<ExecutiveDashboardResponse>(cacheKey) : null;
      if (cached) {
        setExecutiveData(cached);
        dataRef.current = cached;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const reqId = ++requestRef.current;
      const hasExistingData = Boolean(dataRef.current || cached);

      setLoadingExecutive(!hasExistingData);
      setExecutiveError(null);

      try {
        const response = await getExecutiveDashboard(
          { start: safePeriod.start, end: safePeriod.end },
          { signal: controller.signal }
        );
        if (reqId !== requestRef.current) return null;
        startTransition(() => {
          setExecutiveData(response);
        });
        dataRef.current = response;
        writeDashboardCache<ExecutiveDashboardResponse>(cacheKey, response, 180_000);
        return response;
      } catch (error: unknown) {
        if (isAbortError(error) || reqId !== requestRef.current) return null;
        setExecutiveError(errorMessage(error, "Erro ao carregar operação real"));
        return null;
      } finally {
        if (reqId === requestRef.current) setLoadingExecutive(false);
      }
    },
    [activeClientId, cacheKey, enabled, isAuthenticated, safePeriod.end, safePeriod.start]
  );

  useEffect(() => {
    if (!enabled || !isAuthenticated || !activeClientId) return;
    void reloadExecutive();
    return () => {
      abortRef.current?.abort();
    };
  }, [activeClientId, enabled, isAuthenticated, reloadExecutive]);

  return { executiveData, loadingExecutive, executiveError, reloadExecutive };
}
