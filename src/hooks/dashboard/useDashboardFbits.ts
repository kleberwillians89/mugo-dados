import { useCallback, useEffect, useMemo, useState } from "react";
import { getFbitsOrders, getFbitsOrdersSummary } from "../../app/api";
import type { FbitsOrdersResponse, FbitsOrdersSummaryResponse } from "../../app/types";
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

function friendlyError(error: unknown) {
  console.warn("[fbits-dashboard]", error);
  return "A leitura oficial de vendas não ficou disponível agora.";
}

type FbitsCachePayload = {
  summary: FbitsOrdersSummaryResponse | null;
  orders: FbitsOrdersResponse | null;
};

export default function useDashboardFbits({ isAuthenticated, activeClientId, period }: Params) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
  const rangeKey = useMemo(
    () =>
      buildDashboardCacheKey("fbits", {
        clientId: activeClientId,
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, safePeriod.end, safePeriod.start]
  );
  const cachedInitial = useMemo(
    () => (activeClientId ? readDashboardCache<FbitsCachePayload>(rangeKey) : null),
    [activeClientId, rangeKey]
  );
  const [fbitsData, setFbitsData] = useState<FbitsOrdersSummaryResponse | null>(
    cachedInitial?.summary || null
  );
  const [fbitsOrders, setFbitsOrders] = useState<FbitsOrdersResponse | null>(
    cachedInitial?.orders || null
  );
  const [loadingFbits, setLoadingFbits] = useState(false);
  const [fbitsError, setFbitsError] = useState<string | null>(null);

  useEffect(() => {
    if (cachedInitial) {
      setFbitsData(cachedInitial.summary);
      setFbitsOrders(cachedInitial.orders);
    }
    setFbitsError(null);
  }, [cachedInitial, rangeKey]);

  const reloadFbits = useCallback(async (options?: { force?: boolean }) => {
    if (!isAuthenticated || !activeClientId) return null;
    const cached = options?.force ? null : readDashboardCache<FbitsCachePayload>(rangeKey);
    if (cached) {
      setFbitsData(cached.summary);
      setFbitsOrders(cached.orders);
    }
    setLoadingFbits(!cached && !cachedInitial);
    setFbitsError(null);
    try {
      const [summary, orders] = await Promise.allSettled([
        getFbitsOrdersSummary({
          start: safePeriod.start,
          end: safePeriod.end,
        }),
        getFbitsOrders({
          start: safePeriod.start,
          end: safePeriod.end,
        }),
      ]);
      if (summary.status === "rejected") throw summary.reason;
      setFbitsData(summary.value);
      let nextOrders = cached?.orders || cachedInitial?.orders || null;
      if (orders.status === "fulfilled") {
        setFbitsOrders(orders.value);
        nextOrders = orders.value;
      } else {
        console.warn("[fbits-orders]", orders.reason);
      }
      writeDashboardCache<FbitsCachePayload>(
        rangeKey,
        { summary: summary.value, orders: nextOrders || null },
        180_000
      );
      return summary.value;
    } catch (error: unknown) {
      setFbitsError(friendlyError(error));
      return null;
    } finally {
      setLoadingFbits(false);
    }
  }, [activeClientId, cachedInitial, isAuthenticated, rangeKey, safePeriod.end, safePeriod.start]);

  useEffect(() => {
    void reloadFbits();
  }, [reloadFbits]);

  return {
    fbitsData,
    fbitsOrders,
    fbitsError,
    loadingFbits,
    reloadFbits,
  };
}
