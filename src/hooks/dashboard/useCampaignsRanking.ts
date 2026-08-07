import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getCampaignsRanking } from "../../app/api";
import type { CampaignsListResponse } from "../../app/types";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "./cache";

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

export default function useCampaignsRanking({
  isAuthenticated,
  activeClientId,
  activeConnectionId,
  enabled = true,
  period,
}: Params) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
  const resolvedConnectionId = useMemo(() => String(activeConnectionId || "").trim(), [activeConnectionId]);
  const cacheKey = useMemo(
    () =>
      buildDashboardCacheKey("campaigns-ranking", {
        clientId: activeClientId,
        connectionId: resolvedConnectionId || "-",
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, resolvedConnectionId, safePeriod.end, safePeriod.start]
  );
  const cachedInitial = useMemo(
    () => (resolvedConnectionId ? readDashboardCache<CampaignsListResponse>(cacheKey) : null),
    [cacheKey, resolvedConnectionId]
  );

  const [campaignsData, setCampaignsData] = useState<CampaignsListResponse | null>(cachedInitial);
  const [loadingCampaigns, setLoadingCampaigns] = useState(false);
  const [campaignsError, setCampaignsError] = useState<string | null>(null);
  const requestRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const dataRef = useRef<CampaignsListResponse | null>(cachedInitial);
  const cacheKeyRef = useRef(cacheKey);

  useEffect(() => {
    dataRef.current = campaignsData;
  }, [campaignsData]);

  if (cacheKeyRef.current !== cacheKey) {
    cacheKeyRef.current = cacheKey;
    abortRef.current?.abort();
    requestRef.current += 1;
    const next = resolvedConnectionId ? cachedInitial : null;
    dataRef.current = next;
    setCampaignsData(next);
    setCampaignsError(null);
  }

  const reloadCampaigns = useCallback(async () => {
    if (!isAuthenticated || !activeClientId || !resolvedConnectionId || !enabled) return null;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const reqId = ++requestRef.current;
    setLoadingCampaigns(!dataRef.current);
    setCampaignsError(null);
    try {
      const response = await getCampaignsRanking(
        { start: safePeriod.start, end: safePeriod.end },
        { connectionId: resolvedConnectionId, limit: 8, signal: controller.signal }
      );
      if (reqId !== requestRef.current) return null;
      startTransition(() => setCampaignsData(response));
      dataRef.current = response;
      writeDashboardCache<CampaignsListResponse>(cacheKey, response, 180_000);
      return response;
    } catch (error: unknown) {
      if (isAbortError(error) || reqId !== requestRef.current) return null;
      setCampaignsError(errorMessage(error, "Erro ao carregar campanhas"));
      return null;
    } finally {
      if (reqId === requestRef.current) setLoadingCampaigns(false);
    }
  }, [activeClientId, cacheKey, enabled, isAuthenticated, resolvedConnectionId, safePeriod.end, safePeriod.start]);

  useEffect(() => {
    if (!enabled || !isAuthenticated || !activeClientId || !resolvedConnectionId) return;
    void reloadCampaigns();
    return () => {
      abortRef.current?.abort();
    };
  }, [activeClientId, enabled, isAuthenticated, reloadCampaigns, resolvedConnectionId]);

  return { campaignsData, loadingCampaigns, campaignsError, reloadCampaigns };
}
