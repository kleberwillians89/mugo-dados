/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getClientDataHealth } from "./api";
import { useOptionalPeriod } from "./PeriodContext";
import { getSelectedPeriodRange } from "./periodRange";
import { DATA_HEALTH_CHANGED, type DataHealthResponse } from "./dataHealth";

type Value = { data: DataHealthResponse | null; loading: boolean; error: boolean; reload: () => Promise<void> };
export const DataHealthContext = createContext<Value | null>(null);
export function useDataHealth() { return useContext(DataHealthContext); }

/** One bounded persisted read per client/period; no polling or provider sync. */
export function DataHealthProvider({ clientId, enabled, children }: {clientId: string; enabled: boolean; children: ReactNode}) {
  const context = useOptionalPeriod();
  const { start, end } = getSelectedPeriodRange(context?.period);
  const key = `${clientId}:${start}:${end}`;
  const sequence = useRef(0);
  const pending = useRef<{key: string; id: number; promise: Promise<void>; again: boolean} | null>(null);
  const [state, setState] = useState<{key: string; data: DataHealthResponse | null; loading: boolean; error: boolean}>({key: "", data: null, loading: true, error: false});
  const reload = useCallback((): Promise<void> => {
    if (!enabled || !clientId) return Promise.resolve();
    if (pending.current?.key === key && pending.current.id === sequence.current) return pending.current.promise;
    const id = ++sequence.current;
    setState(previous => ({key, data: previous.key === key ? previous.data : null, loading: true, error: false}));
    const entry = {key, id, promise: Promise.resolve(), again: false};
    entry.promise = (async () => {
      try {
        const data = await getClientDataHealth(clientId, {start, end});
        if (id !== sequence.current) return;
        if (data.client_id !== clientId || data.period.start !== start || data.period.end !== end) throw new Error("Freshness scope mismatch");
        setState({key, data, loading: false, error: false});
      } catch { if (id === sequence.current) setState(previous => ({key, data: previous.key === key ? previous.data : null, loading: false, error: true})); }
      finally {
        if (pending.current === entry) pending.current = null;
        // A sync may finish while an older status GET is in flight. Read once more,
        // coalescing all notifications without polling or trusting the old response.
        if (entry.again && id === sequence.current) void reload();
      }
    })();
    pending.current = entry;
    return entry.promise;
  }, [clientId, enabled, end, key, start]);
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void reload(); });
    const changed = (event: Event) => {
      const detail = (event as CustomEvent<{clientId: string}>).detail;
      if (detail?.clientId === clientId) {
        if (pending.current?.key === key) pending.current.again = true;
        else void reload();
      }
    };
    window.addEventListener(DATA_HEALTH_CHANGED, changed);
    return () => { cancelled = true; sequence.current += 1; window.removeEventListener(DATA_HEALTH_CHANGED, changed); };
  }, [clientId, key, reload]);
  const value = useMemo(() => ({data: enabled && state.key === key ? state.data : null,
    loading: enabled && (state.key !== key || state.loading), error: state.key === key && state.error, reload}), [enabled, key, reload, state]);
  return <DataHealthContext.Provider value={value}>{children}</DataHealthContext.Provider>;
}
