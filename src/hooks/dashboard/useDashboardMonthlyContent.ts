import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getMediaMonthly } from "../../app/api";
import type { MediaMonthlyItem } from "../../app/types";
import type { DashboardPeriod } from "./period";
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

type MonthlyCachePayload = {
  months: MediaMonthlyItem[];
};

function arrayOrEmpty<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export default function useDashboardMonthlyContent({
  isAuthenticated,
  activeClientId,
  activeConnectionId,
  enabled = true,
  period,
}: Params) {
  void period;
  const resolvedConnectionId = useMemo(
    () => String(activeConnectionId || "").trim(),
    [activeConnectionId]
  );
  const cacheKey = useMemo(
    () =>
      buildDashboardCacheKey("media-monthly", {
        clientId: activeClientId,
        connectionId: resolvedConnectionId || "-",
        extra: "all-time",
      }),
    [activeClientId, resolvedConnectionId]
  );
  const cachedInitial = useMemo(() => {
    const cached = resolvedConnectionId
      ? readDashboardCache<MonthlyCachePayload>(cacheKey)
      : null;
    return cached
      ? { months: arrayOrEmpty<MediaMonthlyItem>(cached.months) }
      : null;
  }, [cacheKey, resolvedConnectionId]);

  const [monthlyRows, setMonthlyRows] = useState<MediaMonthlyItem[]>(cachedInitial?.months || []);
  const [loadingMonthly, setLoadingMonthly] = useState(false);
  const [refreshingMonthly, setRefreshingMonthly] = useState(false);
  const [monthlyError, setMonthlyError] = useState<string | null>(null);
  const [monthlyUpdatedAt, setMonthlyUpdatedAt] = useState<string | null>(null);
  const requestRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const rowsRef = useRef<MediaMonthlyItem[]>(cachedInitial?.months || []);

  useEffect(() => {
    rowsRef.current = monthlyRows;
  }, [monthlyRows]);

  useEffect(() => {
    if (resolvedConnectionId) {
      if (cachedInitial) {
        const nextRows = cachedInitial.months || [];
        setMonthlyRows(nextRows);
        rowsRef.current = nextRows;
      }
      setMonthlyError(null);
      return;
    }
    setMonthlyRows([]);
    rowsRef.current = [];
    setMonthlyError(null);
    setLoadingMonthly(false);
    setRefreshingMonthly(false);
    setMonthlyUpdatedAt(null);
  }, [cachedInitial, resolvedConnectionId]);

  const reloadMonthly = useCallback(
    async (options?: { force?: boolean }) => {
      if (!isAuthenticated || !activeClientId) return [] as MediaMonthlyItem[];
      if (!resolvedConnectionId) {
        setMonthlyRows([]);
        rowsRef.current = [];
        setMonthlyError(null);
        setLoadingMonthly(false);
        setRefreshingMonthly(false);
        setMonthlyUpdatedAt(null);
        return [] as MediaMonthlyItem[];
      }

      const force = !!options?.force;
      if (!enabled && !force) {
        return rowsRef.current;
      }
      const cached = !force ? readDashboardCache<MonthlyCachePayload>(cacheKey) : null;
      if (cached) {
        const cachedMonths = arrayOrEmpty<MediaMonthlyItem>(cached.months);
        setMonthlyRows(cachedMonths);
        rowsRef.current = cachedMonths;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const reqId = ++requestRef.current;
      const hasExistingRows = rowsRef.current.length > 0 || Boolean(cached?.months?.length);

      setLoadingMonthly(!hasExistingRows);
      setRefreshingMonthly(hasExistingRows);
      setMonthlyError(null);

      try {
        const response = await getMediaMonthly(
          3650,
          {
            connectionId: resolvedConnectionId,
            signal: controller.signal,
          }
        );
        if (reqId !== requestRef.current) return [] as MediaMonthlyItem[];
        const rows = arrayOrEmpty<MediaMonthlyItem>(response.months);
        startTransition(() => {
          setMonthlyRows(rows);
        });
        rowsRef.current = rows;
        setMonthlyUpdatedAt(new Date().toISOString());
        writeDashboardCache<MonthlyCachePayload>(cacheKey, { months: rows }, 300_000);
        return rows;
      } catch (error: unknown) {
        if (isAbortError(error) || reqId !== requestRef.current) return [] as MediaMonthlyItem[];
        setMonthlyError(errorMessage(error, "Erro ao carregar série mensal"));
        return [] as MediaMonthlyItem[];
      } finally {
        if (reqId === requestRef.current) {
          setLoadingMonthly(false);
          setRefreshingMonthly(false);
        }
      }
    },
    [activeClientId, cacheKey, enabled, isAuthenticated, resolvedConnectionId]
  );

  useEffect(() => {
    if (!enabled || !isAuthenticated || !activeClientId || !resolvedConnectionId) return;
    void reloadMonthly();
    return () => {
      abortRef.current?.abort();
    };
  }, [activeClientId, enabled, isAuthenticated, reloadMonthly, resolvedConnectionId]);

  return {
    monthlyRows,
    loadingMonthly,
    refreshingMonthly,
    monthlyError,
    monthlyUpdatedAt,
    reloadMonthly,
  };
}
