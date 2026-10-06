import { markReadStage } from "./readPerformance";
/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useOptionalPeriod, type Period } from "./PeriodContext";
import { getSelectedPeriodRange } from "./periodRange";
import { supabase } from "./supabase";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "../hooks/dashboard/cache";
import useFirstUsefulData from "../hooks/useFirstUsefulData";

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
export type DashboardSnapshot = { daily: DashboardDailyMetric[]; sources: DashboardSourceSnapshot[]; campaigns: DashboardCampaignMetric[]; products: DashboardProductMetric[]; fetchedAt: string; queryCount: number; campaignsLoaded?: boolean; productsLoaded?: boolean; secondaryLoading?: boolean; campaignsLoading?: boolean; productsLoading?: boolean; secondaryErrors?: string[] };

type Value = { range?: Period; readRange?: (range: Period, manual?: boolean) => Promise<DashboardSnapshot | null>; scopeKey?: string; snapshot: DashboardSnapshot | null; loading: boolean; refreshing: boolean; error: string | null; refetch: (options?: { afterCurrent?: boolean }) => Promise<DashboardSnapshot | null> };
// Exportado só para o harness de revisão visual (src/design-review) simular
// carregamento e erro do read model; o runtime usa apenas o provider abaixo.
export type DashboardDataValue = Value;
export const DashboardDataContext = createContext<Value | null>(null);
const inFlightSnapshots = new Map<string, Promise<DashboardSnapshot | null>>();
const PAGE_SIZE = 1000;

export function DashboardDataProvider({ clientId, tenantReady, enabled, children, period, resources = "both" }: { clientId: string; tenantReady: boolean; enabled: boolean; children: ReactNode; period?: Period; resources?: "none" | "campaigns" | "products" | "both" }) {
  const context = useOptionalPeriod();
  const selected = getSelectedPeriodRange(period ?? context?.period);
  const start = selected.start, end = selected.end;
  const scopeKey = `${clientId}:${start}:${end}`;
  const currentScope = useRef(scopeKey);
  useLayoutEffect(() => { currentScope.current = scopeKey; }, [scopeKey]);
  const [state, setState] = useState<{ key: string; snapshot: DashboardSnapshot | null; loading: boolean; error: string | null }>({ key: scopeKey, snapshot: null, loading: true, error: null });
  const restored = enabled && tenantReady ? readDashboardCache<DashboardSnapshot>(buildDashboardCacheKey("read-model-period-v3", { clientId, start, end })) : null;
  const baseSnapshot = (state.key === scopeKey ? state.snapshot : null) || restored;
  const snapshot = useMemo(() => baseSnapshot ? { ...baseSnapshot,
    campaignsLoading: Boolean(baseSnapshot.campaignsLoading || ((resources === "campaigns" || resources === "both") && baseSnapshot.campaignsLoaded === false)),
    productsLoading: Boolean(baseSnapshot.productsLoading || ((resources === "products" || resources === "both") && baseSnapshot.productsLoaded === false)),
  } : null, [baseSnapshot, resources]);
  useFirstUsefulData(scopeKey, enabled && tenantReady && Boolean(snapshot));

  const readRange = useCallback(async (range: Period, manual = false): Promise<DashboardSnapshot | null> => {
    if (!enabled || !tenantReady || !clientId || !supabase) return null;
    const key = buildDashboardCacheKey("read-model-period-v3", { clientId, start: range.start, end: range.end });
    let cached = readDashboardCache<DashboardSnapshot>(key);
    const needCampaigns = resources === "campaigns" || resources === "both";
    const needProducts = resources === "products" || resources === "both";
    const complete = (value: DashboardSnapshot) => (!needCampaigns || value.campaignsLoaded !== false) && (!needProducts || value.productsLoaded !== false);
    if (cached && !manual && !cached.secondaryLoading && complete(cached)) return cached;
    const prior = inFlightSnapshots.get(key);
    if (prior) {
      const priorValue = await prior;
      if (!priorValue || complete(priorValue)) return priorValue;
      if (inFlightSnapshots.get(key) === prior) inFlightSnapshots.delete(key);
      cached = readDashboardCache<DashboardSnapshot>(key);
    }
    const database = supabase;
    const request = (async () => {
      markReadStage("snapshot_request_start");
      let queryCount = 0;
      async function read(table: string, dated: boolean, columns = "*") {
        const rows: Record<string, unknown>[] = [];
        for (let offset = 0; offset < 200_000; offset += PAGE_SIZE) {
          let query = database.from(table).select(columns).eq("client_id", clientId);
          if (dated) query = query.gte("metric_date", range.start).lte("metric_date", range.end).order("metric_date");
          // Ordem estável nos empates garante paginação de campanhas/produtos.
          if (table === "dashboard_campaign_metrics") query = query.order("provider").order("campaign_id");
          if (table === "dashboard_product_metrics") query = query.order("product_id");
          const result = await query.range(offset, offset + PAGE_SIZE - 1);
          queryCount += 1;
          if (result.error) throw new Error("Falha ao ler o snapshot.");
          const page = result.data || [];
          rows.push(...page as unknown as Record<string, unknown>[]);
          if (page.length < PAGE_SIZE) return rows;
        }
        throw new Error("Paginação do read model incompleta.");
      }
      const [daily, sources] = cached && !manual ? [cached.daily, cached.sources] : await Promise.all([
        read("dashboard_daily_metrics", true),
        read("dashboard_source_snapshots", false, "provider,last_success_at,data_max_available,data_min_available,updated_at"),
      ]);
      const primary = { daily, sources, campaigns: cached?.campaigns || [], products: cached?.products || [], fetchedAt: new Date().toISOString(), queryCount, campaignsLoaded: cached?.campaignsLoaded ?? false, productsLoaded: cached?.productsLoaded ?? false, secondaryLoading: needCampaigns || needProducts, campaignsLoading: needCampaigns, productsLoading: needProducts } as unknown as DashboardSnapshot;
      const publish = (next: DashboardSnapshot) => {
        writeDashboardCache(key, next, 15 * 60_000);
        if (currentScope.current === `${clientId}:${range.start}:${range.end}`)
          setState({ key: currentScope.current, snapshot: next, loading: false, error: null });
      };
      publish(primary);
      markReadStage("snapshot_ready");
      let next = primary;
      const secondary = async (resource: "campaigns" | "products", table: string) => {
        try {
          const rows = await read(table, true);
          next = { ...next, [resource]: rows, [`${resource}Loaded`]: true, [`${resource}Loading`]: false, queryCount };
        } catch {
          next = { ...next, [`${resource}Loaded`]: true, [`${resource}Loading`]: false, secondaryErrors: [...(next.secondaryErrors || []), resource], queryCount };
        }
        publish(next);
      };
      await Promise.all([...(needCampaigns ? [secondary("campaigns", "dashboard_campaign_metrics")] : []), ...(needProducts ? [secondary("products", "dashboard_product_metrics")] : [])]);
      next = { ...next, secondaryLoading: false };
      writeDashboardCache(key, next, 15 * 60_000);
      markReadStage("secondary_data_ready");
      return next;
    })();
    inFlightSnapshots.set(key, request);
    try { return await request; } finally { if (inFlightSnapshots.get(key) === request) inFlightSnapshots.delete(key); }
  }, [clientId, enabled, resources, tenantReady]);

  const load = useCallback(async (manual = false, afterCurrent = false) => {
    const requestedScope = scopeKey;
    const key = buildDashboardCacheKey("read-model-period-v3", { clientId, start, end });
    if (afterCurrent) { try { await inFlightSnapshots.get(key); } catch { /* releitura após erro */ } }
    setState(previous => ({ key: requestedScope, snapshot: previous.key === requestedScope ? previous.snapshot || readDashboardCache<DashboardSnapshot>(key) : readDashboardCache<DashboardSnapshot>(key), loading: true, error: null }));
    try {
      const next = await readRange({ start, end }, manual);
      if (currentScope.current === requestedScope) setState({ key: requestedScope, snapshot: next, loading: false, error: null });
      return next;
    } catch {
      if (currentScope.current === requestedScope) setState(previous => ({ ...previous, loading: false, error: "Falha ao ler o snapshot." }));
      return null;
    }
  }, [clientId, end, readRange, scopeKey, start]);
  const refetch = useCallback((options?: { afterCurrent?: boolean }) => load(true, options?.afterCurrent), [load]);
  useEffect(() => { void load(); }, [load]);
  const value = useMemo(() => ({ snapshot, range: { start, end }, readRange, scopeKey,
    loading: !snapshot && (state.key !== scopeKey || state.loading),
    refreshing: state.key === scopeKey && state.loading && Boolean(snapshot),
    error: state.key === scopeKey ? state.error : null, refetch }), [end, readRange, refetch, scopeKey, snapshot, start, state]);
  return <DashboardDataContext.Provider value={value}>{children}</DashboardDataContext.Provider>;
}

export function useDashboardSnapshot(start?: string, end?: string) {
  const value = useContext(DashboardDataContext);
  if (!value) throw new Error("useDashboardSnapshot requires DashboardDataProvider");
  const outside = Boolean(start && end && value.range && (start !== value.range.start || end !== value.range.end));
  const key = `${value.scopeKey}:${start}:${end}`;
  const [extra, setExtra] = useState<{ key: string; snapshot: DashboardSnapshot | null; loading: boolean; error: string | null }>({ key: "", snapshot: null, loading: true, error: null });
  const read = value.readRange;
  const currentKey = useRef(key);
  useLayoutEffect(() => { currentKey.current = key; }, [key]);
  const reload = useCallback(async (manual = false) => {
    if (!outside || !start || !end || !read || currentKey.current !== key) return null;
    setExtra({ key, snapshot: null, loading: true, error: null });
    try {
      const next = await read({ start, end }, manual);
      if (currentKey.current === key) setExtra({ key, snapshot: next, loading: false, error: null });
      return next;
    } catch { if (currentKey.current === key) setExtra({ key, snapshot: null, loading: false, error: "Falha ao ler o período de comparação." }); return null; }
  }, [end, key, outside, read, start]);
  useEffect(() => {
    let cancelled = false;
    if (outside && start && end && read) {
      void read({ start, end }).then(snapshot => {
        if (!cancelled) setExtra({ key, snapshot, loading: false, error: null });
      }).catch(() => { if (!cancelled) setExtra({ key, snapshot: null, loading: false, error: "Falha ao ler o período de comparação." }); });
    }
    return () => { cancelled = true; };
  }, [end, key, outside, read, start]);
  const snapshot = outside ? extra.key === key ? extra.snapshot : null : value.snapshot;
  const daily = useMemo(() => snapshot?.daily.filter(row => (!start || row.metric_date >= start) && (!end || row.metric_date <= end)) || [], [end, start, snapshot]);
  const campaigns = useMemo(() => snapshot?.campaigns.filter(row => (!start || row.metric_date >= start) && (!end || row.metric_date <= end)) || [], [end, start, snapshot]);
  const products = useMemo(() => snapshot?.products.filter(row => (!start || row.metric_date >= start) && (!end || row.metric_date <= end)) || [], [end, start, snapshot]);
  return { ...value, snapshot, daily, campaigns, products, sources: snapshot?.sources || [],
    loading: outside ? extra.key !== key || extra.loading : value.loading,
    error: outside ? extra.key === key ? extra.error : null : value.error,
    refetch: outside ? () => reload(true) : value.refetch };
}
