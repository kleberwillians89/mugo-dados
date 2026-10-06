import { useCallback, useEffect, useRef, useState } from "react";
import { readDashboardCache, writeDashboardCache, buildDashboardCacheKey } from "./dashboard/cache";
import { readOnce } from "./dashboard/readOnce";
import { getActiveClientId } from "../app/activeClient";
import { getGoals, type Goal } from "../app/goals";
export default function useGoals(clientId: string, start: string, end: string, enabled = true) {
  const key = buildDashboardCacheKey("goals", { clientId, start, end });
  const cached = readDashboardCache<Goal[]>(key);
  const [state, setState] = useState<{ key: string; goals: Goal[] }>({ key, goals: cached || [] });
  const [issue, setIssue] = useState<{ key: string; message: string } | null>(null);
  const [loading, setLoading] = useState(!cached && enabled);
  const generation = useRef(0);
  const load = useCallback(async () => {
    if (!clientId || !enabled) return;
    const request = ++generation.current;
    setLoading(!readDashboardCache<Goal[]>(key)); setIssue(null);
    try {
      if (!readDashboardCache<Goal[]>(key)) {
        const base = await readOnce(`${key}:base`, () => getGoals(start, end, false));
        if (request !== generation.current || getActiveClientId() !== clientId) return;
        if (base.client_id !== clientId) throw new Error("A leitura de metas não corresponde à empresa ativa.");
        setState({ key, goals: base.goals.filter(goal => goal.client_id === clientId) });
        setLoading(false);
      }
      const result = await readOnce(key, () => getGoals(start, end));
      if (request !== generation.current || getActiveClientId() !== clientId) return;
      if (result.client_id !== clientId) throw new Error("A leitura de metas não corresponde à empresa ativa.");
      const goals = result.goals.filter((goal) => goal.client_id === clientId);
      writeDashboardCache(key, goals, 180_000);
      setState({ key, goals });
    } catch (cause) {
      if (request === generation.current && getActiveClientId() === clientId) setIssue({ key, message: cause instanceof Error ? cause.message : "Não foi possível ler as metas." });
    } finally { if (request === generation.current) setLoading(false); }
  }, [clientId, enabled, end, key, start]);
  const invalidate = useCallback(() => { generation.current++; }, []);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void load(); });
    return () => { cancelled = true; invalidate(); };
  }, [enabled, load, invalidate]);
  return { goals: state.key === key ? state.goals : cached || [], error: issue?.key === key ? issue.message : null, loading: enabled && !cached && (state.key !== key || loading), reload: load };
}
