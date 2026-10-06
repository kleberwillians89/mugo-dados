import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { listGenericConnections, type GenericConnection } from "../../app/api";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "./cache";
import { readOnce } from "./readOnce";

export function ga4IsReady(rows: GenericConnection[]) {
  return rows.some(row => row.provider === "ga4" && !row.disconnected_at
    && !["disconnected", "token_expired", "reauth_required", "not_configured"].includes(row.status)
    && row.capabilities?.ga4_configured === true);
}
/** Somente configuração persistida, pela leitura autorizada ao membro. */
export default function useGa4Readiness(clientId: string, enabled: boolean) {
  const key = buildDashboardCacheKey("ga4-readiness", {clientId});
  const cached = readDashboardCache<boolean>(key);
  const [state, setState] = useState<{key:string; ready:boolean|null; error:string|null}>({key, ready:cached, error:null});
  const current = useRef(key); useLayoutEffect(() => {current.current = key;}, [key]);
  useEffect(() => {
    if (!enabled || !clientId || readDashboardCache<boolean>(key) !== null) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      void readOnce(key, () => listGenericConnections()).then(result => {
        if (current.current !== key || result.client_id !== clientId) return;
        const ready = ga4IsReady(result.connections || []);
        writeDashboardCache(key, ready, 120_000);
        if (!cancelled) setState({key, ready, error:null});
      }).catch(() => { if (!cancelled && current.current === key) setState({key,ready:null,error:"Não foi possível verificar a configuração GA4."}); });
    });
    return () => {cancelled = true;};
  }, [clientId, enabled, key]);
  return {ready: enabled ? (state.key === key ? state.ready : cached) : false, error:state.key === key ? state.error : null};
}
