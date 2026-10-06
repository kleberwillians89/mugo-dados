import { markReadStage } from "../app/readPerformance";
import { useEffect, useRef } from "react";

/** Medição real no navegador após commit do read model, sem métricas/PII. */
export default function useFirstUsefulData(scope: string, ready: boolean) {
  const measurement = useRef({ scope: "", started: 0, emitted: false });
  useEffect(() => {
    if (measurement.current.scope !== scope) {
      measurement.current = { scope, started: performance.now(), emitted: false };
    }
    if (!ready || measurement.current.emitted) return;
    let cancelled = false;
    const emit = () => {
      if (cancelled || measurement.current.scope !== scope) return;
      measurement.current.emitted = true;
      markReadStage("first_useful_data");
      console.info("[performance][first_useful_data]", {
        dataset: "dashboard_read_model", duration_ms: Math.round(performance.now() - measurement.current.started),
      });
    };
    if (typeof requestAnimationFrame === "undefined") {
      queueMicrotask(emit);
      return () => { cancelled = true; };
    }
    const frame = requestAnimationFrame(emit);
    return () => { cancelled = true; cancelAnimationFrame(frame); };
  }, [ready, scope]);
}
