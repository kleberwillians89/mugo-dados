import { useState, type ReactNode } from "react";
import type { Period } from "../../app/PeriodContext";

/** Mantém somente a última composição utilizável DO MESMO tenant. */
export default function PeriodTransition({tenantId, period, ready, children}: {tenantId:string; period:Period; ready:boolean; children:ReactNode}) {
  const [previous, setPrevious] = useState<{tenantId:string; period:Period; children:ReactNode}|null>(null);
  const retained = previous?.tenantId === tenantId ? previous : null;
  if (ready && (previous?.children !== children || previous?.tenantId !== tenantId)) setPrevious({tenantId, period, children});
  const tenantPending = previous && previous.tenantId !== tenantId && !ready;
  const pending = retained && !ready;
  const changedPeriod = retained && (retained.period.start !== period.start || retained.period.end !== period.end);
  return <>
    {tenantPending ? <p role="status">Carregando a leitura desta empresa...</p> : pending ? <p role="status">{changedPeriod ? "Atualizando período..." : "Atualizando leitura..."} Exibindo {retained.period.start} — {retained.period.end} até a nova leitura ficar disponível.</p> : null}
    {tenantPending ? null : pending ? retained.children : children}
  </>;
}
