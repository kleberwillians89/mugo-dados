import { useCallback, useEffect, useRef, useState } from "react";
import { getActiveClientId } from "../app/activeClient";
import { getGoals, type Goal } from "../app/goals";
export default function useGoals(clientId: string, start: string, end: string, enabled = true) {
  const key = `${clientId}:${start}:${end}`;
  const [state, setState] = useState<{ key: string; goals: Goal[] }>({ key, goals: [] });
  const [issue, setIssue] = useState<{ key: string; message: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const load = useCallback(async () => {
    if (!clientId || !enabled) return;
    const request = ++generation.current;
    setLoading(true); setIssue(null);
    try {
      const result = await getGoals(start, end);
      if (request !== generation.current || getActiveClientId() !== clientId) return;
      if (result.client_id !== clientId) throw new Error("A leitura de metas não corresponde à empresa ativa.");
      setState({ key, goals: result.goals.filter((goal) => goal.client_id === clientId) });
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
  return { goals: state.key === key ? state.goals : [], error: issue?.key === key ? issue.message : null, loading, reload: load };
}
