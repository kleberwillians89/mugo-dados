import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getMediaMonthly } from "../../app/api";
import { readOnce } from "./readOnce";
import type { MediaMonthlyItem } from "../../app/types";
import { ensureDashboardPeriod } from "./period";
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
  const selected = useMemo(() => ensureDashboardPeriod(period), [period]);
  const resolvedConnectionId = useMemo(
    () => String(activeConnectionId || "").trim(),
    [activeConnectionId]
  );
  const cacheKey = useMemo(
    () =>
      buildDashboardCacheKey("media-monthly", {
        clientId: activeClientId,
        connectionId: resolvedConnectionId || "-",
        start: selected.start, end: selected.end,
      }),
    [activeClientId, resolvedConnectionId, selected.start, selected.end]
  );
  const cachedInitial = useMemo(() => {
    const cached = readDashboardCache<MonthlyCachePayload>(cacheKey);
    return cached
      ? { months: arrayOrEmpty<MediaMonthlyItem>(cached.months) }
      : null;
  }, [cacheKey]);

  const [monthlyRows, setMonthlyRows] = useState<MediaMonthlyItem[]>(cachedInitial?.months || []);
  const [loadingMonthly, setLoadingMonthly] = useState(false);
  const [refreshingMonthly, setRefreshingMonthly] = useState(false);
  const [monthlyError, setMonthlyError] = useState<string | null>(null);
  const [monthlyUpdatedAt, setMonthlyUpdatedAt] = useState<string | null>(null);
  const requestRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const rowsRef = useRef<MediaMonthlyItem[]>(cachedInitial?.months || []);
  const cacheKeyRef = useRef(cacheKey);

  useEffect(() => {
    rowsRef.current = monthlyRows;
  }, [monthlyRows]);

  // Troca de empresa/conexão nunca pode deixar a série mensal do tenant
  // anterior visível — nem por um frame, e nem indefinidamente quando o
  // novo tenant ainda não tem cache (antes, esse caso não limpava nada).
  // Reset síncrono durante o render, não em useEffect.
  if (cacheKeyRef.current !== cacheKey) {
    cacheKeyRef.current = cacheKey;
    abortRef.current?.abort();
    requestRef.current += 1;
    const nextRows = cachedInitial?.months || [];
    setMonthlyRows(nextRows);
    rowsRef.current = nextRows;
    setMonthlyError(null);
  }

  const reloadMonthly = useCallback(
    async (options?: { force?: boolean }) => {
      if (!isAuthenticated || !activeClientId) return [] as MediaMonthlyItem[];
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
        const load = () => getMediaMonthly(
          { start: selected.start, end: selected.end },
          {
            connectionId: resolvedConnectionId,
            clientId: activeClientId,
            signal: options?.force ? controller.signal : undefined,
          }
        );
        const response = options?.force ? await load() : await readOnce(cacheKey, load);
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
    [activeClientId, cacheKey, enabled, isAuthenticated, resolvedConnectionId, selected.start, selected.end]
  );

  useEffect(() => {
    if (!enabled || !isAuthenticated || !activeClientId) return;
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void reloadMonthly(); });
    return () => {
      cancelled = true;
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
