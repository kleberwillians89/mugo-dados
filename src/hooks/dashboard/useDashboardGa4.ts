import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getGa4Campaigns, getGa4Channels } from "../../app/api";
import type { Ga4CampaignRow, Ga4ChannelRow, Ga4ReportResponse } from "../../app/types";
import { useDashboardSnapshot } from "../../app/DashboardDataContext";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";

export default function useDashboardGa4({
  isAuthenticated,
  activeClientId,
  period,
}: {
  isAuthenticated: boolean;
  activeClientId: string;
  period?: DashboardPeriod | null;
}) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
  const model = useDashboardSnapshot(safePeriod.start, safePeriod.end);
  const [channels, setChannels] = useState<Ga4ChannelRow[]>([]);
  const [campaigns, setCampaigns] = useState<Ga4CampaignRow[]>([]);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const loadDetails = useCallback(async () => {
    if (!isAuthenticated || !activeClientId) return;
    const requestId = ++requestRef.current;
    const selectedPeriod = { start: safePeriod.start, end: safePeriod.end };
    try {
      const [channelResponse, campaignResponse] = await Promise.all([
        getGa4Channels(selectedPeriod, { clientId: activeClientId }),
        getGa4Campaigns(selectedPeriod, { clientId: activeClientId }),
      ]);
      if (requestId !== requestRef.current) return;
      setChannels(channelResponse.items);
      setCampaigns(campaignResponse.items);
      setDetailsError(null);
    } catch (error) {
      if (requestId !== requestRef.current) return;
      setDetailsError(error instanceof Error ? error.message : "Não foi possível carregar canais e campanhas.");
    }
  }, [activeClientId, isAuthenticated, safePeriod.end, safePeriod.start]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadDetails();
    }, 0);
    return () => {
      window.clearTimeout(timer);
      requestRef.current += 1;
    };
  }, [loadDetails]);

  const ga4Report = useMemo<Ga4ReportResponse | null>(() => {
    if (!activeClientId || (!model.snapshot && model.loading)) return null;
    const daily = model.daily.map((row) => ({
      date: row.metric_date,
      sessions: Number(row.ga4_sessions || 0),
      active_users: Number(row.ga4_users || 0),
      total_users: Number(row.ga4_users || 0),
      event_count: Number(row.ga4_events || 0),
      ecommerce_purchases: Number(row.ga4_purchases || 0),
      purchase_revenue: Number(row.ga4_revenue || 0),
      total_revenue: Number(row.ga4_revenue || 0),
      view_item_count: 0,
      add_to_cart_count: 0,
      begin_checkout_count: 0,
      purchase_count: Number(row.ga4_purchases || 0),
    }));
    const total = (key: keyof (typeof daily)[number]) =>
      daily.reduce((value, row) => value + Number(row[key] || 0), 0);
    const source = model.sources.find((item) => item.provider === "ga4");
    const emptyGroup = (key: string, title: string) => ({
      key,
      title,
      description: "",
      total_events: 0,
      total_users: 0,
      items: [],
    });
    return {
      ok: true,
      client_id: activeClientId,
      property_id: "read-model",
      period: { start: safePeriod.start, end: safePeriod.end, days: daily.length },
      summary: {
        sessions: total("sessions"),
        active_users: total("active_users"),
        total_users: total("total_users"),
        event_count: total("event_count"),
        purchases: total("ecommerce_purchases"),
        purchase_revenue: total("purchase_revenue"),
        total_revenue: total("total_revenue"),
        average_daily_active_users: daily.length ? total("active_users") / daily.length : 0,
        average_daily_total_users: daily.length ? total("total_users") / daily.length : 0,
      },
      funnel: {
        view_item: 0,
        add_to_cart: 0,
        begin_checkout: 0,
        add_payment_info: 0,
        purchase: total("ecommerce_purchases"),
      },
      commerce_journey: {
        summary: {
          view_item: 0,
          add_to_cart: 0,
          begin_checkout: 0,
          add_payment_info: 0,
          purchase: total("ecommerce_purchases"),
          add_to_cart_rate: 0,
          checkout_rate: 0,
          payment_info_rate: 0,
          purchase_rate: 0,
          purchase_rate_from_view_item: 0,
        },
        items: [],
      },
      behavior: emptyGroup("behavior", "Comportamento"),
      engagement: emptyGroup("engagement", "Engajamento"),
      merchandising: emptyGroup("merchandising", "Produtos"),
      trends: { daily },
      channels,
      campaigns,
      events: [],
      meta: {
        last_synced_at: source?.last_success_at || null,
        data_available: daily.length > 0 || channels.length > 0 || campaigns.length > 0,
        daily_rows: daily.length,
        channel_rows: channels.length,
        campaign_rows: campaigns.length,
        event_rows: 0,
      },
    };
  }, [activeClientId, campaigns, channels, model.daily, model.loading, model.snapshot, model.sources, safePeriod.end, safePeriod.start]);

  const reloadGa4 = useCallback(async (options?: { force?: boolean }) => {
    void options;
    await Promise.all([model.refetch(), loadDetails()]);
    return ga4Report;
  }, [ga4Report, loadDetails, model]);

  return {
    ga4Report,
    loadingGa4: model.loading && !ga4Report,
    refreshingGa4: model.refreshing,
    ga4Error: model.error || detailsError,
    ga4UpdatedAt: model.sources.find((item) => item.provider === "ga4")?.last_success_at || null,
    reloadGa4,
  };
}
