import type { Period } from "../../app/PeriodContext";
import { getSelectedPeriodRange } from "../../app/periodRange";

export type DashboardPeriod = Pick<Period, "start" | "end">;

export function fallbackDashboardPeriod(days = 30): DashboardPeriod {
  const safeDays = Math.max(1, Math.floor(days || 30));
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - (safeDays - 1));
  return getSelectedPeriodRange({ start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) });
}

export function ensureDashboardPeriod(
  period: Partial<DashboardPeriod> | null | undefined
): DashboardPeriod {
  return getSelectedPeriodRange(period || fallbackDashboardPeriod(30));
}

/**
 * Janela imediatamente anterior, com a mesma duração em dias — usada só
 * para comparação narrativa (nunca inventa histórico: se o período tiver
 * 8 dias, compara contra os 8 dias imediatamente anteriores).
 */
export function previousDashboardPeriod(period: DashboardPeriod): DashboardPeriod {
  const start = new Date(`${period.start}T00:00:00Z`);
  const end = new Date(`${period.end}T00:00:00Z`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return period;
  }
  const days = Math.max(1, Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1);
  const previousEnd = new Date(start.getTime() - 86_400_000);
  const previousStart = new Date(previousEnd.getTime() - (days - 1) * 86_400_000);
  return {
    start: previousStart.toISOString().slice(0, 10),
    end: previousEnd.toISOString().slice(0, 10),
  };
}
