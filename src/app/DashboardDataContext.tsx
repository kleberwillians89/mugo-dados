/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { supabase } from "./supabase";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "../hooks/dashboard/cache";

export type DashboardDailyMetric = {
  client_id: string; metric_date: string; updated_at: string;
  shopify_net_revenue: number | null; shopify_gross_revenue: number | null;
  shopify_orders: number | null; shopify_paid_orders: number | null; shopify_customers: number | null; shopify_customer_keys: string[] | null; shopify_refunds: number | null;
  shopify_orders_created?: number | null; shopify_orders_non_cancelled?: number | null;
  shopify_pending_orders?: number | null; shopify_sales_revenue?: number | null;
  meta_spend: number | null; meta_attributed_revenue: number | null; meta_purchases: number | null;
  meta_impressions: number | null; meta_reach: number | null; meta_clicks: number | null; meta_link_clicks: number | null; meta_video_views: number | null;
  google_ads_spend: number | null; google_ads_conversion_value: number | null; google_ads_conversions: number | null;
  google_ads_impressions: number | null; google_ads_clicks: number | null;
  ga4_sessions: number | null; ga4_users: number | null; ga4_revenue: number | null; ga4_purchases: number | null; ga4_events: number | null;
  instagram_reach: number | null; instagram_impressions: number | null; instagram_interactions: number | null;
  instagram_profile_views: number | null; instagram_website_clicks: number | null; instagram_followers: number | null;
};

export type DashboardCampaignMetric = Record<string, string | number | null> & { metric_date: string; provider: string; campaign_id: string };
export type DashboardProductMetric = Record<string, string | number | null> & { metric_date: string; product_id: string };
export type DashboardSourceSnapshot = { provider: string; last_success_at: string | null; data_max_available: string | null; data_min_available: string | null; updated_at: string };
export type DashboardSnapshot = { daily: DashboardDailyMetric[]; sources: DashboardSourceSnapshot[]; campaigns: DashboardCampaignMetric[]; products: DashboardProductMetric[]; fetchedAt: string; queryCount: number };

type Value = { snapshot: DashboardSnapshot | null; loading: boolean; refreshing: boolean; error: string | null; refetch: (options?: { afterCurrent?: boolean }) => Promise<DashboardSnapshot | null> };
// Exportado só para o harness de revisão visual (src/design-review) simular
// carregamento e erro do read model; o runtime usa apenas o provider abaixo.
export type DashboardDataValue = Value;
export const DashboardDataContext = createContext<Value | null>(null);
const bootstrapCompleted = new Set<string>();
const inFlightSnapshots = new Map<string, Promise<DashboardSnapshot | null>>();

function currentYearStart() {
  const value = new Date();
  return `${value.getFullYear()}-01-01`;
}

export function DashboardDataProvider({ clientId, tenantReady, enabled, children }: { clientId: string; tenantReady: boolean; enabled: boolean; children: ReactNode }) {
  const cacheKey = useMemo(() => buildDashboardCacheKey("read-model-ytd-v2", { clientId }), [clientId]);
  const cached = useMemo(() => clientId ? readDashboardCache<DashboardSnapshot>(cacheKey) : null, [cacheKey, clientId]);
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(cached);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const currentClient = useRef(clientId);
  const snapshotRef = useRef(snapshot);
  const generationRef = useRef(0);
  snapshotRef.current = snapshot;

  if (currentClient.current !== clientId) {
    generationRef.current += 1;
    currentClient.current = clientId;
    bootstrapCompleted.delete(clientId);
    setSnapshot(cached);
    setError(null);
  }

  const loadSnapshot = useCallback(async (manual: boolean) => {
    if (!enabled || !tenantReady || !clientId || !supabase) return null;
    if (!manual && bootstrapCompleted.has(clientId)) return snapshotRef.current;
    const existingRequest = inFlightSnapshots.get(clientId);
    if (existingRequest) return existingRequest;
    const requestedClientId = clientId;
    const requestedGeneration = generationRef.current;
    const request = (async (): Promise<DashboardSnapshot | null> => {
    const hadSnapshot = Boolean(snapshotRef.current || readDashboardCache<DashboardSnapshot>(cacheKey));
    setLoading(!hadSnapshot);
    setRefreshing(hadSnapshot);
    setError(null);
    performance.mark("dashboard-start");
    const start = currentYearStart();
    const [dailyResult, sourcesResult, campaignsResult, productsResult] = await Promise.all([
      supabase.from("dashboard_daily_metrics").select("*").eq("client_id", clientId).gte("metric_date", start).order("metric_date"),
      supabase.from("dashboard_source_snapshots").select("provider,last_success_at,data_max_available,data_min_available,updated_at").eq("client_id", clientId),
      supabase.from("dashboard_campaign_metrics").select("*").eq("client_id", clientId).gte("metric_date", start).order("metric_date"),
      supabase.from("dashboard_product_metrics").select("*").eq("client_id", clientId).gte("metric_date", start).order("metric_date").limit(1000),
    ]);
    try {
      const firstError = [dailyResult.error, sourcesResult.error, campaignsResult.error, productsResult.error].find(Boolean);
      if (firstError) throw firstError;
      const next: DashboardSnapshot = {
        daily: (dailyResult.data || []) as DashboardDailyMetric[],
        sources: (sourcesResult.data || []) as DashboardSourceSnapshot[],
        campaigns: (campaignsResult.data || []) as DashboardCampaignMetric[],
        products: (productsResult.data || []) as DashboardProductMetric[],
        fetchedAt: new Date().toISOString(), queryCount: 4,
      };
      if (currentClient.current !== requestedClientId || generationRef.current !== requestedGeneration) return null;
      setSnapshot(next);
      writeDashboardCache(cacheKey, next, 15 * 60_000);
      performance.mark("snapshot-ready");
      performance.measure("time_to_snapshot_ms", "dashboard-start", "snapshot-ready");
      const duration = performance.getEntriesByName("time_to_snapshot_ms").at(-1)?.duration;
      if (import.meta.env.DEV) console.info("[dashboard_snapshot]", { client_id: clientId, time_to_snapshot_ms: Math.round(duration || 0), supabase_queries: 4 });
      bootstrapCompleted.add(requestedClientId);
      return next;
    } catch (cause) {
      if (currentClient.current === requestedClientId && generationRef.current === requestedGeneration) setError(cause instanceof Error ? cause.message : "Falha ao ler o snapshot.");
      return null;
    } finally {
      if (currentClient.current === requestedClientId && generationRef.current === requestedGeneration) { setLoading(false); setRefreshing(false); }
    }
    })();
    inFlightSnapshots.set(clientId, request);
    try { return await request; } finally { if (inFlightSnapshots.get(clientId) === request) inFlightSnapshots.delete(clientId); }
  }, [cacheKey, clientId, enabled, tenantReady]);

  const refetch = useCallback(async (options?: { afterCurrent?: boolean }) => {
    if (options?.afterCurrent) {
      const prior = inFlightSnapshots.get(clientId);
      if (prior) await prior;
    }
    return loadSnapshot(true);
  }, [clientId, loadSnapshot]);

  useEffect(() => { void loadSnapshot(false); }, [loadSnapshot]);
  const value = useMemo(() => ({ snapshot, loading, refreshing, error, refetch }), [error, loading, refetch, refreshing, snapshot]);
  return <DashboardDataContext.Provider value={value}>{children}</DashboardDataContext.Provider>;
}

export function useDashboardSnapshot(start?: string, end?: string) {
  const value = useContext(DashboardDataContext);
  if (!value) throw new Error("useDashboardSnapshot requires DashboardDataProvider");
  const daily = useMemo(() => value.snapshot?.daily.filter((row) => (!start || row.metric_date >= start) && (!end || row.metric_date <= end)) || [], [end, start, value.snapshot]);
  const campaigns = useMemo(() => value.snapshot?.campaigns.filter((row) => (!start || row.metric_date >= start) && (!end || row.metric_date <= end)) || [], [end, start, value.snapshot]);
  const products = useMemo(() => value.snapshot?.products.filter((row) => (!start || row.metric_date >= start) && (!end || row.metric_date <= end)) || [], [end, start, value.snapshot]);
  return { ...value, daily, campaigns, products, sources: value.snapshot?.sources || [] };
}
