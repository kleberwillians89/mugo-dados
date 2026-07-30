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
