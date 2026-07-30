import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getGa4Report } from "../../app/api";
import type { Ga4ReportResponse } from "../../app/types";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";
import {
  buildDashboardCacheKey,
  readDashboardCache,
  writeDashboardCache,
} from "./cache";

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

  useEffect(() => {
    dataRef.current = ga4Report;
  }, [ga4Report]);

  useEffect(() => {
    if (!cachedInitial) return;
    setGa4Report(cachedInitial);
    dataRef.current = cachedInitial;
  }, [cachedInitial]);

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

  return {
    ga4Report,
    loadingGa4,
    refreshingGa4,
    ga4Error,
    ga4UpdatedAt,
    reloadGa4,
  };
}
