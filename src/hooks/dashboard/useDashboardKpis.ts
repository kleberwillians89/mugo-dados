import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getDashboard } from "../../app/api";
import type { DashboardResponse } from "../../app/types";
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
  period?: DashboardPeriod | null;
};

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

export default function useDashboardKpis({
  isAuthenticated,
  activeClientId,
  activeConnectionId,
  period,
}: Params) {
  const safePeriod = useMemo(
    () => ensureDashboardPeriod(period),
    [period]
  );
  const cacheKey = useMemo(
    () =>
      buildDashboardCacheKey("kpis", {
        clientId: activeClientId,
        connectionId: activeConnectionId,
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, activeConnectionId, safePeriod.end, safePeriod.start]
  );
  const requestRef = useRef(0);
  const [dash, setDash] = useState<DashboardResponse | null>(() =>
    readDashboardCache<DashboardResponse>(cacheKey)
  );
  const [loadingDash, setLoadingDash] = useState(false);
  const [dashError, setDashError] = useState<string | null>(null);

  const reloadDashboard = useCallback(async (options?: { force?: boolean }) => {
    if (!isAuthenticated || !activeClientId) return null;
    const force = !!options?.force;

    if (!force) {
      const cached = readDashboardCache<DashboardResponse>(cacheKey);
      if (cached) {
        setDash(cached);
        return cached;
      }
    }

    const reqId = ++requestRef.current;
    setLoadingDash(true);
    setDashError(null);
    try {
      const next = await getDashboard(
        { start: safePeriod.start, end: safePeriod.end },
        { connectionId: activeConnectionId }
      );
      if (reqId !== requestRef.current) return null;
      setDash(next);
      writeDashboardCache(cacheKey, next, 180_000);
      return next;
    } catch (error: unknown) {
      if (reqId !== requestRef.current) return null;
      setDashError(errorMessage(error, "Erro ao carregar dashboard"));
      return null;
    } finally {
      if (reqId === requestRef.current) {
        setLoadingDash(false);
      }
    }
  }, [activeClientId, activeConnectionId, cacheKey, isAuthenticated, safePeriod.end, safePeriod.start]);

  useEffect(() => {
    if (!isAuthenticated || !activeClientId) return;
    void reloadDashboard();
  }, [isAuthenticated, activeClientId, activeConnectionId, cacheKey, reloadDashboard]);

  return {
    dash,
    setDash,
    loadingDash,
    dashError,
    reloadDashboard,
  };
}

export type { DashboardPeriod };
