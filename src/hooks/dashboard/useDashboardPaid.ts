import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getDashboardPaid } from "../../app/api";
import type { PaidDashboardResponse } from "../../app/types";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";
import {
  buildDashboardCacheKey,
  readDashboardCache,
  writeDashboardCache,
} from "./cache";

type Params = {
  isAuthenticated: boolean;
  activeClientId: string;
  activeConnectionId?: string | null;
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

export default function useDashboardPaid({
  isAuthenticated,
  activeClientId,
  activeConnectionId,
  enabled = true,
  period,
}: Params) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
  const resolvedConnectionId = useMemo(
    () => String(activeConnectionId || "").trim(),
    [activeConnectionId]
  );
  const cacheKey = useMemo(
    () =>
      buildDashboardCacheKey("paid", {
        clientId: activeClientId,
        connectionId: resolvedConnectionId || "-",
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, resolvedConnectionId, safePeriod.end, safePeriod.start]
  );
  const cachedInitial = useMemo(
    () => (resolvedConnectionId ? readDashboardCache<PaidDashboardResponse>(cacheKey) : null),
    [cacheKey, resolvedConnectionId]
  );

  const [paidData, setPaidData] = useState<PaidDashboardResponse | null>(cachedInitial);
  const [loadingPaid, setLoadingPaid] = useState(false);
  const [refreshingPaid, setRefreshingPaid] = useState(false);
  const [paidError, setPaidError] = useState<string | null>(null);
  const [paidUpdatedAt, setPaidUpdatedAt] = useState<string | null>(null);
  const requestRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const dataRef = useRef<PaidDashboardResponse | null>(cachedInitial);

  useEffect(() => {
    dataRef.current = paidData;
  }, [paidData]);

  useEffect(() => {
    if (resolvedConnectionId) {
      if (cachedInitial) {
        setPaidData(cachedInitial);
        dataRef.current = cachedInitial;
      } else {
        setPaidData(null);
        dataRef.current = null;
      }
      setPaidError(null);
      return;
    }
    setPaidData(null);
    dataRef.current = null;
    setPaidError(null);
    setLoadingPaid(false);
    setRefreshingPaid(false);
    setPaidUpdatedAt(null);
  }, [cachedInitial, resolvedConnectionId]);

  const reloadPaid = useCallback(
    async (options?: { force?: boolean }) => {
      if (!isAuthenticated || !activeClientId) return null;
      if (!resolvedConnectionId) {
        setPaidData(null);
        dataRef.current = null;
        setPaidError(null);
        setLoadingPaid(false);
        setRefreshingPaid(false);
        setPaidUpdatedAt(null);
        return null;
      }

      const force = !!options?.force;
      if (!enabled && !force) {
        return dataRef.current;
      }
      const cached = !force ? readDashboardCache<PaidDashboardResponse>(cacheKey) : null;
      if (cached) {
        setPaidData(cached);
        dataRef.current = cached;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const reqId = ++requestRef.current;
      const hasExistingData = Boolean(dataRef.current || cached);

      setLoadingPaid(!hasExistingData);
      setRefreshingPaid(hasExistingData);
      setPaidError(null);

      try {
        const response = await getDashboardPaid(
          {
            start: safePeriod.start,
            end: safePeriod.end,
          },
          {
            connectionId: resolvedConnectionId,
            signal: controller.signal,
          }
        );
        if (reqId !== requestRef.current) return null;
        startTransition(() => {
          setPaidData(response);
        });
        dataRef.current = response;
        setPaidUpdatedAt(new Date().toISOString());
        writeDashboardCache<PaidDashboardResponse>(cacheKey, response, 180_000);
        return response;
      } catch (error: unknown) {
        if (isAbortError(error) || reqId !== requestRef.current) return null;
        setPaidError(errorMessage(error, "Erro ao carregar dados de Ads"));
        return null;
      } finally {
        if (reqId === requestRef.current) {
          setLoadingPaid(false);
          setRefreshingPaid(false);
        }
      }
    },
    [activeClientId, cacheKey, enabled, isAuthenticated, resolvedConnectionId, safePeriod.end, safePeriod.start]
  );

  useEffect(() => {
    if (!enabled || !isAuthenticated || !activeClientId || !resolvedConnectionId) return;
    void reloadPaid();
    return () => {
      abortRef.current?.abort();
    };
  }, [activeClientId, enabled, isAuthenticated, reloadPaid, resolvedConnectionId]);

  return {
    paidData,
    loadingPaid,
    refreshingPaid,
    paidError,
    paidUpdatedAt,
    reloadPaid,
  };
}
