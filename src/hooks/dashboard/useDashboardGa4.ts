import { useCallback, useEffect, useLayoutEffect, useRef, useState, useMemo } from "react";
import { readOnce } from "./readOnce";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "./cache";
import { getGa4Report } from "../../app/api";
import type { Ga4ReportResponse } from "../../app/types";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";

/** O relatório existente lê fatos persistidos da propriedade do tenant na janela pedida. */
export default function useDashboardGa4({ isAuthenticated, activeClientId, period }: {
  isAuthenticated: boolean; activeClientId: string; period?: DashboardPeriod | null;
}) {
  const selected = useMemo(() => ensureDashboardPeriod(period), [period]);
  const key = buildDashboardCacheKey("ga4-report", { clientId: activeClientId, start: selected.start, end: selected.end });
  const cached = readDashboardCache<Ga4ReportResponse>(key);
  const currentKey = useRef(key);
  useLayoutEffect(() => { currentKey.current = key; }, [key]);
  const request = useRef(0);
  const [state, setState] = useState<{ key: string; report: Ga4ReportResponse | null; loading: boolean; error: string | null }>({ key, report: cached, loading: !cached, error: null });
  const report = (state.key === key ? state.report : null) || cached;
  const load = useCallback(async () => {
    const sequence = ++request.current;
    if (!isAuthenticated || !activeClientId) return null;
    setState(previous => ({ key, report: (previous.key === key ? previous.report : null) || readDashboardCache<Ga4ReportResponse>(key), loading: true, error: null }));
    try {
      const next = await readOnce(key, () => getGa4Report({ start: selected.start, end: selected.end }, { clientId: activeClientId }));
      if (currentKey.current === key) writeDashboardCache(key, next, 180_000);
      if (sequence === request.current && currentKey.current === key) setState({ key, report: next, loading: false, error: null });
      return next;
    } catch (cause) {
      if (sequence === request.current && currentKey.current === key) setState(previous => ({ ...previous, loading: false, error: cause instanceof Error ? cause.message : "Não foi possível carregar o GA4." }));
      return null;
    }
  }, [activeClientId, isAuthenticated, key, selected.end, selected.start]);
  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => { window.clearTimeout(timer); request.current += 1; };
  }, [load]);
  const reloadGa4 = useCallback(async (options?: { force?: boolean }) => { void options; return load(); }, [load]);
  return { ga4Report: report, loadingGa4: !report && (state.key !== key || state.loading),
    refreshingGa4: Boolean(report && state.loading), ga4Error: state.key === key ? state.error : null,
    ga4UpdatedAt: report?.meta.last_synced_at || null, reloadGa4 };
}
