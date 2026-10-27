import { useEffect, useState } from "react";
import { nextAutoRefreshLabel } from "../../app/autoRefreshSchedule";

/** "· próxima atualização automática por volta das 19:05" (atualiza a cada minuto). */
export default function NextAutoRefresh({ provider }: { provider: string }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const label = nextAutoRefreshLabel(provider, now);
  if (!label) return null;
  return <span className="ds-nextAutoRefresh" data-testid={`next-auto-refresh-${provider}`}> · {label}</span>;
}
