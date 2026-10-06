import { useCallback, useEffect, useState } from "react";

/** Leituras secundárias só começam quando a seção entra na área visível. */
export default function useSectionDemand(scope: string, ready: boolean): { observe: (element: HTMLElement | null) => void; enabled: boolean } {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const observe = useCallback((node: HTMLElement | null) => { setElement(node); }, []);
  const [requestedScope, request] = useState<string | null>(null);
  const enabled = ready && requestedScope === scope;
  useEffect(() => {
    if (!ready || !element || enabled) return;
    if (typeof IntersectionObserver === "undefined") {
      let cancelled = false;
      queueMicrotask(() => { if (!cancelled) request(scope); });
      return () => { cancelled = true; };
    }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        request(scope);
        observer.disconnect();
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [element, enabled, ready, scope]);
  return { observe, enabled };
}
