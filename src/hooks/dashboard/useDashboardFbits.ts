import { useCallback, useEffect, useMemo, useState } from "react";
import { getFbitsOrders, getFbitsOrdersSummary, getShopifyReport, listGenericConnections } from "../../app/api";
import type { FbitsOrdersResponse, FbitsOrdersSummaryResponse } from "../../app/types";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";
import {
  buildDashboardCacheKey,
  readDashboardCache,
  writeDashboardCache,
} from "./cache";
import { resolveCommerceConnection } from "../../app/connectionManager";
import { getSelectedConnectionId } from "../../app/connectionState";
export { resolveCommerceConnection } from "../../app/connectionManager";

type Params = {
  isAuthenticated: boolean;
  activeClientId: string;
  period?: DashboardPeriod | null;
  /** Provider já resolvido pela aba Ecommerce: "fbits" usa só endpoints FBITS. */
  provider?: "fbits" | null;
};

function friendlyError(error: unknown) {
  console.warn("[fbits-dashboard]", error);
  return "A leitura oficial de vendas não ficou disponível agora.";
}

type FbitsCachePayload = {
  summary: FbitsOrdersSummaryResponse | null;
  orders: FbitsOrdersResponse | null;
};

export default function useDashboardFbits({ isAuthenticated, activeClientId, period, provider = null }: Params) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
  const fbitsOnly = provider === "fbits";
  const rangeKey = useMemo(
    () =>
      // Namespace próprio no modo FBITS: o cache "fbits" legado pode conter
      // um resumo mapeado da Shopify para o mesmo tenant.
      buildDashboardCacheKey(fbitsOnly ? "fbits-tenant" : "fbits", {
        clientId: activeClientId,
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, fbitsOnly, safePeriod.end, safePeriod.start]
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

  const loadFbitsEndpoints = useCallback(async (cached: FbitsCachePayload | null) => {
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
  }, [cachedInitial, rangeKey, safePeriod.end, safePeriod.start]);

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
      if (fbitsOnly) return await loadFbitsEndpoints(cached);
      const connectionResponse = await listGenericConnections();
      const selectedId = getSelectedConnectionId(activeClientId, "shopify") ||
        getSelectedConnectionId(activeClientId, "fbits");
      const commerceConnection = resolveCommerceConnection(connectionResponse.connections, selectedId);
      if (!commerceConnection) {
        const empty: FbitsOrdersSummaryResponse = {
          ok: true,
          connected: false,
          client_id: activeClientId,
          period: { start: safePeriod.start, end: safePeriod.end },
          summary: { receita_oficial: 0, pedidos: 0, ticket_medio: 0, clientes: 0, produtos_vendidos: 0 },
          message: "Nenhuma plataforma de e-commerce conectada.",
        };
        setFbitsData(empty);
        setFbitsOrders(null);
        return empty;
      }
      if (commerceConnection.provider === "shopify") {
        const report = await getShopifyReport({ start: safePeriod.start, end: safePeriod.end });
        const summary: FbitsOrdersSummaryResponse = {
          ok: report.ok,
          connected: true,
          client_id: report.client_id,
          period: { start: report.period.start, end: report.period.end },
          summary: {
            receita_oficial: report.summary.revenue_total,
            pedidos: report.summary.orders,
            ticket_medio: report.summary.average_ticket,
            clientes: report.summary.customers,
            produtos_vendidos: report.top_products.reduce((total, item) => total + item.quantity_sold, 0),
          },
          message: "Fonte: Shopify",
        };
        setFbitsData(summary);
        setFbitsOrders(null);
        writeDashboardCache<FbitsCachePayload>(rangeKey, { summary, orders: null }, 180_000);
        return summary;
      }
      return await loadFbitsEndpoints(cached);
    } catch (error: unknown) {
      setFbitsError(friendlyError(error));
      return null;
    } finally {
      setLoadingFbits(false);
    }
  }, [activeClientId, cachedInitial, fbitsOnly, isAuthenticated, loadFbitsEndpoints, rangeKey, safePeriod.end, safePeriod.start]);

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
