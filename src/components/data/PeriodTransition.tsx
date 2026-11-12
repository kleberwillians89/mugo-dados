import { useState, type ReactNode } from "react";
import type { Period } from "../../app/PeriodContext";
import PageSkeleton from "./PageSkeleton";

/** Mantém somente a última composição utilizável DO MESMO tenant. */
export default function PeriodTransition({tenantId, period, ready, children}: {tenantId:string; period:Period; ready:boolean; children:ReactNode}) {
  const [previous, setPrevious] = useState<{tenantId:string; period:Period; children:ReactNode}|null>(null);
  const retained = previous?.tenantId === tenantId ? previous : null;
  if (ready && (previous?.children !== children || previous?.tenantId !== tenantId)) setPrevious({tenantId, period, children});
  const tenantPending = previous && previous.tenantId !== tenantId && !ready;
  const changedPeriod = retained && (retained.period.start !== period.start || retained.period.end !== period.end);
  // Only a period change needs the old composition. Reusing old React nodes
  // within the same period freezes live controls and hides finished errors.
  const pending = retained && !ready && changedPeriod;
  // Troca de empresa ou de período: esqueleto no lugar dos números antigos (nada de dado velho piscando na tela).
  if (tenantPending) return <PageSkeleton label="Carregando a leitura desta empresa…" />;
  if (pending) return <PageSkeleton label={`Atualizando para ${period.start} — ${period.end}…`} />;
  return <>{children}</>;
}
