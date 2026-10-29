import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getProviderRefreshStatus, type ProviderRefreshStatus } from "../app/api";
import { isSyncInProgress } from "../app/syncOrchestrator";
import { DATA_HEALTH_CHANGED } from "../app/dataHealth";

type Phase = "checking" | "running" | "cooldown" | "ready" | "denied";
const unavailable = "Não foi possível verificar o acesso. Os dados anteriores continuam disponíveis.";

/** Observes existing backend leases; never retries a provider POST. */
export function useProviderRefresh(clientId: string, provider: ProviderRefreshStatus["provider"], period: {start: string; end: string}, enabled: boolean) {
  const {start, end} = period;
  const key = `${clientId}:${provider}:${start}:${end}:${enabled}`;
  const scope = useRef(key);
  const generation = useRef(0);
  const busy = useRef(false);
  const observedRunning = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const channel = useRef<BroadcastChannel | null>(null);
  const pendingCheck = useRef<{key: string; version: number; promise: Promise<boolean>} | null>(null);
  const [result, setResult] = useState<{key: string; message: string; outcome: "success" | "failed"} | null>(null);
  const [state, setState] = useState<{key: string; phase: Phase; error: string | null; cooldown?: number}>({key, phase: "checking", error: null});
  const check = useCallback(async (): Promise<boolean> => {
    if (!enabled || !clientId || scope.current !== key) return false;
    const version = generation.current;
    if (pendingCheck.current?.key === key && pendingCheck.current.version === version) return pendingCheck.current.promise;
    const entry = {key, version, promise: Promise.resolve(false)};
    pendingCheck.current = entry;
    entry.promise = (async () => {
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
        setState({key, phase, error: null, cooldown: result.cooldown_seconds});
        // Terminal readiness is refreshed on focus, visibility and cross-tab updates.\n        // Avoid an endless idle poll against Supabase after the job has finished.\n        if (phase !== "ready") {\n          const delay = phase === "cooldown" && result.cooldown_seconds > 30 ? 15_000 : 5_000;\n          timer.current = setTimeout(() => void check(), delay);\n        }
        return phase === "ready";
      } catch (cause) {
        if (scope.current !== key || generation.current !== version) return false;
        const denied = cause instanceof ApiError && [401, 403].includes(cause.status);
        setState({key, phase: denied ? "denied" : "checking", error: denied ? "Seu perfil não tem permissão para atualizar os dados." : unavailable});
        if (!denied) timer.current = setTimeout(() => void check(), 15_000);
        return false;
      }
      finally {if (pendingCheck.current === entry) pendingCheck.current = null;}
    })();
    return entry.promise;
  }, [clientId, enabled, key, start, end, provider]);
  useEffect(() => {
    scope.current = key;
    busy.current = false;
    observedRunning.current = false;
    let alive = true;
    queueMicrotask(() => { if (alive) void check(); });
    const focus = () => { if (!busy.current) void check(); };
    const visible = () => {if (document.visibilityState === "visible") focus();};
    window.addEventListener("focus", focus);
    document.addEventListener("visibilitychange", visible);
    try {
      if (typeof window.BroadcastChannel === "function") {
        const updates = new window.BroadcastChannel("mugo-refresh-status");
        channel.current = updates;
        updates.onmessage = event => {if (event.data?.clientId === clientId && event.data?.provider === provider) focus();};
      }
    } catch { /* Server leases remain authoritative if cross-tab signals are unavailable. */ }
    return () => { generation.current += 1; alive = false; scope.current = ""; clearTimeout(timer.current); channel.current?.close(); channel.current = null; window.removeEventListener("focus", focus); document.removeEventListener("visibilitychange", visible); };
  }, [check, key, clientId, provider]);
  const run = useCallback(async (task: () => Promise<void>) => {
    if (!enabled || busy.current || scope.current !== key) return;
    const version = generation.current;
    busy.current = true; // Synchronous latch, before authorization or React rerender.
    clearTimeout(timer.current);
    setState({key, phase: "checking", error: null});
    setResult(null);
    const notify = () => {try {channel.current?.postMessage({clientId, provider});} catch { /* Advisory signal cannot fail or replace the refresh result. */ }};
    let started = false;
    try {
      // The local latch must not be mistaken for an existing server job.
      const result = await getProviderRefreshStatus(clientId, provider, {start, end});
      if (scope.current !== key || generation.current !== version) return;
      if (result.client_id !== clientId || result.provider !== provider || result.authorized !== true ||
          typeof result.running !== "boolean" || !Number.isFinite(result.cooldown_seconds) || result.cooldown_seconds < 0) throw new Error("Invalid refresh scope");
      if (result.running || result.cooldown_seconds > 0 || isSyncInProgress({clientId, provider})) {
        observedRunning.current = result.running || isSyncInProgress({clientId, provider});
        setState({key, phase: result.running || isSyncInProgress({clientId, provider}) ? "running" : "cooldown", error: null, cooldown: result.cooldown_seconds});
        timer.current = setTimeout(() => void check(), 5_000);
        return;
      }
      started = true;
      setState({key, phase: "running", error: null});
      notify();
      await task();
      if (scope.current === key && generation.current === version) setResult({key, outcome: "success", message: "Seus dados foram atualizados."});
    } catch (cause) {
      if (scope.current === key && generation.current === version) {
        if (!started) {
          const denied = cause instanceof ApiError && [401, 403].includes(cause.status);
          setState({key, phase: denied ? "denied" : "checking", error: denied ? "Seu perfil não tem permissão para atualizar os dados." : unavailable});
          if (!denied) timer.current = setTimeout(() => void check(), 15_000);
        } else setResult({key, outcome: "failed", message: "Não foi possível confirmar a atualização. Os dados anteriores continuam disponíveis."});
      }
      throw cause;
    } finally {
      if (scope.current === key && generation.current === version) {
        busy.current = false;
        if (started) {
          await check(); // An HTTP error/abort is not confirmation that backend work ended.
          notify();
        }
      }
    }
  }, [check, clientId, enabled, key, start, end, provider]);
  const phase = state.key === key ? state.phase : "checking";
  const waitMinutes = Math.max(1, Math.ceil((state.cooldown || 0) / 60));
  const waitLabel = `${waitMinutes} ${waitMinutes === 1 ? "minuto" : "minutos"}`;
  const message = phase === "checking" ? "Verificando se é possível iniciar a atualização."
    : phase === "running" ? "Uma atualização está em andamento. Mantendo os dados anteriores."
    : [result?.key === key ? result.message : "", phase === "cooldown" ? `Você poderá atualizar novamente em ${waitLabel}.` : ""].filter(Boolean).join(" ");
  return {run, disabled: !enabled || phase !== "ready", running: phase === "running",
    label: phase === "checking" ? "Verificando acesso..." : phase === "running" ? "Atualizando dados..." : "Atualizar dados",
    error: state.key === key ? state.error : null, phase, message: enabled ? message : "", outcome: result?.key === key ? result.outcome : undefined};
}
