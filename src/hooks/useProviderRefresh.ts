import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getProviderRefreshStatus } from "../app/api";
import { isSyncInProgress } from "../app/syncOrchestrator";
import { DATA_HEALTH_CHANGED } from "../app/dataHealth";

type Phase = "checking" | "running" | "cooldown" | "ready" | "denied";
const unavailable = "Não foi possível verificar o acesso. Os dados anteriores continuam disponíveis.";

/** Observes existing backend leases; never retries a provider POST. */
export function useProviderRefresh(clientId: string, provider: "meta" | "google", period: {start: string; end: string}, enabled: boolean) {
  const {start, end} = period;
  const key = `${clientId}:${provider}:${start}:${end}:${enabled}`;
  const scope = useRef(key);
  const generation = useRef(0);
  const busy = useRef(false);
  const observedRunning = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [state, setState] = useState<{key: string; phase: Phase; error: string | null}>({key, phase: "checking", error: null});
  const check = useCallback(async (): Promise<boolean> => {
    if (!enabled || !clientId || scope.current !== key) return false;
    const version = generation.current;
    clearTimeout(timer.current);
    try {
      const result = await getProviderRefreshStatus(clientId, provider, {start, end});
      if (scope.current !== key || generation.current !== version) return false;
      if (result.client_id !== clientId || result.provider !== provider || result.authorized !== true ||
          typeof result.running !== "boolean" || !Number.isFinite(result.cooldown_seconds) || result.cooldown_seconds < 0) throw new Error("Invalid refresh scope");
      const running = result.running || busy.current || isSyncInProgress({clientId, provider});
      if (observedRunning.current && !running) {
        window.dispatchEvent(new CustomEvent(DATA_HEALTH_CHANGED, {detail: {clientId}}));
      }
      observedRunning.current = running;
      const phase = running ? "running" : result.cooldown_seconds > 0 ? "cooldown" : "ready";
      setState({key, phase, error: null});
      if (phase !== "ready") timer.current = setTimeout(() => void check(), 5_000);
      return phase === "ready";
    } catch (cause) {
      if (scope.current !== key || generation.current !== version) return false;
      const denied = cause instanceof ApiError && [401, 403].includes(cause.status);
      setState({key, phase: denied ? "denied" : "checking", error: denied ? "Seu perfil não tem permissão para atualizar os dados." : unavailable});
      if (!denied) timer.current = setTimeout(() => void check(), 15_000);
      return false;
    }
  }, [clientId, enabled, key, start, end, provider]);
  useEffect(() => {
    scope.current = key;
    busy.current = false;
    observedRunning.current = false;
    let alive = true;
    queueMicrotask(() => { if (alive) void check(); });
    const focus = () => { if (!busy.current) void check(); };
    window.addEventListener("focus", focus);
    return () => { generation.current += 1; alive = false; scope.current = ""; clearTimeout(timer.current); window.removeEventListener("focus", focus); };
  }, [check, key]);
  const run = useCallback(async (task: () => Promise<void>) => {
    if (!enabled || busy.current || scope.current !== key) return;
    const version = generation.current;
    busy.current = true; // Synchronous latch, before authorization or React rerender.
    clearTimeout(timer.current);
    setState({key, phase: "checking", error: null});
    try {
      // The local latch must not be mistaken for an existing server job.
      const result = await getProviderRefreshStatus(clientId, provider, {start, end});
      if (scope.current !== key || generation.current !== version) return;
      if (result.client_id !== clientId || result.provider !== provider || result.authorized !== true ||
          typeof result.running !== "boolean" || !Number.isFinite(result.cooldown_seconds) || result.cooldown_seconds < 0) throw new Error("Invalid refresh scope");
      if (result.running || result.cooldown_seconds > 0 || isSyncInProgress({clientId, provider})) return;
      setState({key, phase: "running", error: null});
      await task();
    } finally {
      if (scope.current === key && generation.current === version) {
        busy.current = false;
        await check(); // An HTTP error/abort is not confirmation that backend work ended.
      }
    }
  }, [check, clientId, enabled, key, start, end, provider]);
  const phase = state.key === key ? state.phase : "checking";
  return {run, disabled: !enabled || phase !== "ready", running: phase === "running",
    label: phase === "checking" ? "Verificando acesso..." : phase === "running" ? "Atualizando dados..." : "Atualizar dados",
    error: state.key === key ? state.error : null};
}
