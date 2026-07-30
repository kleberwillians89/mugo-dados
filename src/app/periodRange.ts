type PeriodLike = {
  start: string;
  end: string;
};

export type SelectedPeriodRange = Pick<PeriodLike, "start" | "end">;

function toDateInput(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseDate(value: string | null | undefined): Date | null {
  const text = String(value || "").trim();
  if (!text) return null;
  const parsed = new Date(`${text}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function fallbackPeriod(days = 30): SelectedPeriodRange {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - (Math.max(1, Math.floor(days || 30)) - 1));
  return {
    start: toDateInput(start),
    end: toDateInput(end),
  };
}

function fixedMonthRange(month?: number | null, year?: number | null): SelectedPeriodRange | null {
  if (!month || !year) return null;
  const safeYear = Math.max(2000, Math.min(2100, Math.floor(year)));
  const safeMonth = Math.max(1, Math.min(12, Math.floor(month)));
  return {
    start: toDateInput(new Date(safeYear, safeMonth - 1, 1)),
    end: toDateInput(new Date(safeYear, safeMonth, 0)),
  };
}

export function getSelectedPeriodRange(
  period?: Partial<PeriodLike> | null,
  month?: number | null,
  year?: number | null
): SelectedPeriodRange {
  const start = parseDate(period?.start);
  const end = parseDate(period?.end);
  if (start && end) {
    return start.getTime() <= end.getTime()
      ? { start: toDateInput(start), end: toDateInput(end) }
      : { start: toDateInput(end), end: toDateInput(start) };
  }

  return fixedMonthRange(month, year) || fallbackPeriod();
}

export function countSelectedPeriodDays(range: SelectedPeriodRange): number {
  const selected = getSelectedPeriodRange(range);
  const start = parseDate(selected.start);
  const end = parseDate(selected.end);
  if (!start || !end) return 30;
  return Math.max(1, Math.floor((end.getTime() - start.getTime()) / 86_400_000) + 1);
}

export function formatSelectedPeriodLabel(range: SelectedPeriodRange): string {
  const selected = getSelectedPeriodRange(range);
  const format = (value: string) =>
    new Date(`${value}T00:00:00`).toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  return `${format(selected.start)}–${format(selected.end)}`;
}
