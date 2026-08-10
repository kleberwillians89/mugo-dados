import { useCallback, useMemo } from "react";
import type { PaidDashboardResponse, PaidTotals } from "../../app/types";
import { useDashboardSnapshot } from "../../app/DashboardDataContext";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";

type Params = { isAuthenticated: boolean; activeClientId: string; activeConnectionId?: string | null; enabled?: boolean; period?: DashboardPeriod | null; filters?: { campaign?: string; adset?: string; ad?: string; platform?: string } };
const sum = (rows: Array<Record<string, unknown>>, key: string) => rows.reduce((total, row) => total + Number(row[key] ?? 0), 0);

export default function useDashboardPaid({ activeClientId, enabled = true, period, filters }: Params) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
  const model = useDashboardSnapshot(safePeriod.start, safePeriod.end);
  const paidData = useMemo<PaidDashboardResponse | null>(() => {
    if (!activeClientId || !enabled || (!model.snapshot && model.loading)) return null;
    const daily = model.daily.map((row) => {
      const spend = row.meta_spend; const revenue = row.meta_attributed_revenue;
      return { date: row.metric_date, spend, revenue, conversions: row.meta_purchases, impressions: row.meta_impressions,
        reach: row.meta_reach, clicks: row.meta_clicks, cpc: spend != null && row.meta_clicks ? spend / row.meta_clicks : null,
        cpm: spend != null && row.meta_impressions ? spend * 1000 / row.meta_impressions : null,
        ctr: row.meta_clicks != null && row.meta_impressions ? row.meta_clicks * 100 / row.meta_impressions : null,
        roas: spend != null && spend > 0 && revenue != null ? revenue / spend : null };
    });
    const numericRows = daily as Array<Record<string, unknown>>;
    const totals: PaidTotals = { spend: sum(numericRows,"spend"), revenue: sum(numericRows,"revenue"), conversions: sum(numericRows,"conversions"),
      impressions: sum(numericRows,"impressions"), reach: sum(numericRows,"reach"), clicks: sum(numericRows,"clicks"), cpc: null,cpm:null,ctr:null,roas:null };
    totals.cpc = totals.spend != null && totals.clicks ? totals.spend / totals.clicks : null;
    totals.cpm = totals.spend != null && totals.impressions ? totals.spend * 1000 / totals.impressions : null;
    totals.ctr = totals.clicks != null && totals.impressions ? totals.clicks * 100 / totals.impressions : null;
    totals.roas = totals.spend != null && totals.spend > 0 && totals.revenue != null ? totals.revenue / totals.spend : null;
    const campaigns = model.campaigns.filter((row) => row.provider === "meta" && (!filters?.campaign || String(row.campaign_id) === filters.campaign));
    const source = model.sources.find((item) => item.provider === "meta");
    return { ok:true, client_id:activeClientId, days:daily.length, date_range:{since:safePeriod.start,until:safePeriod.end},
      has_data:daily.length>0,data_available:daily.length>0,last_sync_at:source?.last_success_at || null,
      row_count:daily.length,first_stat_date:daily[0]?.date || null,last_stat_date:daily.at(-1)?.date || null,
      daily,totals,accounts:[],top_creatives:[], manager_metrics:{link_clicks:sum(model.daily as unknown as Array<Record<string,unknown>>,"meta_link_clicks"),video_views:sum(model.daily as unknown as Array<Record<string,unknown>>,"meta_video_views"),page_engagement:0,post_engagement:0,profile_visits:0},
      sources:{rows:{campaign_daily_stats:campaigns.length,aggregated_rows:daily.length},totals:{consolidated:totals}} };
  }, [activeClientId, enabled, filters, model.campaigns, model.daily, model.loading, model.snapshot, model.sources, safePeriod.end, safePeriod.start]);
  const reloadPaid = useCallback(async (options?: { force?: boolean }) => { void options; return model.refetch() as Promise<unknown> as Promise<PaidDashboardResponse | null>; }, [model]);
  return { paidData, loadingPaid:model.loading && !paidData, refreshingPaid:model.refreshing, paidError:model.error, paidUpdatedAt:model.snapshot?.fetchedAt || null, reloadPaid };
}
