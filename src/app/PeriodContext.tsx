/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { countSelectedPeriodDays, getSelectedPeriodRange } from "./periodRange";

type Period = {
  start: string;
  end: string;
};

type PeriodContextValue = {
  period: Period;
  periodDays: number;
  setPeriod: (next: Period) => void;
  setPresetPeriod: (days: number) => void;
  setCurrentMonthPeriod: () => void;
  setMonthPeriod: (year: number, month: number) => void;
  setDayPeriod: (date: string) => void;
  shiftDayPeriod: (days: number) => void;
};

const STORAGE_KEY = "mugo.period";

function toDateInput(value: Date): string {
  const y = value.getFullYear();
  const m = String(value.getMonth() + 1).padStart(2, "0");
  const d = String(value.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function safeDate(value: string): Date | null {
  const trimmed = String(value || "").trim();
  if (!trimmed) return null;
  const parsed = new Date(`${trimmed}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function defaultPeriod(days = 30): Period {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - (days - 1));
  return {
    start: toDateInput(start),
    end: toDateInput(end),
  };
}

function currentMonthPeriod(): Period {
  const end = new Date();
  const start = new Date(end.getFullYear(), end.getMonth(), 1);
  return {
    start: toDateInput(start),
    end: toDateInput(end),
  };
}

function fixedMonthPeriod(year: number, month: number): Period {
  const safeYear = Math.max(2000, Math.min(2100, Math.floor(year || 0)));
  const safeMonth = Math.max(1, Math.min(12, Math.floor(month || 1)));
  const start = new Date(safeYear, safeMonth - 1, 1);
  const end = new Date(safeYear, safeMonth, 0);
  return {
    start: toDateInput(start),
    end: toDateInput(end),
  };
}

function readStoredPeriod(): Period {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultPeriod();
    const parsed = JSON.parse(raw) as Partial<Period>;
    const start = String(parsed.start || "").trim();
    const end = String(parsed.end || "").trim();
    if (!safeDate(start) || !safeDate(end)) return defaultPeriod();
    return { start, end };
  } catch {
    return defaultPeriod();
  }
}

const PeriodContext = createContext<PeriodContextValue | null>(null);

export function PeriodProvider({ children }: { children: ReactNode }) {
  const [period, setPeriodState] = useState<Period>(() => readStoredPeriod());

  const setPeriod = useCallback((next: Period) => {
    const start = String(next.start || "").trim();
    const end = String(next.end || "").trim();
    const startDate = safeDate(start);
    const endDate = safeDate(end);
    if (!startDate || !endDate) return;

    const normalizedStart = startDate.getTime() <= endDate.getTime() ? start : end;
    const normalizedEnd = startDate.getTime() <= endDate.getTime() ? end : start;

    const normalized: Period = {
      start: normalizedStart,
      end: normalizedEnd,
    };
    setPeriodState(normalized);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
    } catch {
      // no-op
    }
  }, []);

  const setPresetPeriod = useCallback(
    (days: number) => {
      const safeDays = Math.max(1, Math.floor(days || 1));
      setPeriod(defaultPeriod(safeDays));
    },
    [setPeriod]
  );

  const setCurrentMonthPeriod = useCallback(() => {
    setPeriod(currentMonthPeriod());
  }, [setPeriod]);

  const setMonthPeriod = useCallback(
    (year: number, month: number) => {
      setPeriod(fixedMonthPeriod(year, month));
    },
    [setPeriod]
  );

  const setDayPeriod = useCallback((date: string) => {
    setPeriod({ start: date, end: date });
  }, [setPeriod]);

  const shiftDayPeriod = useCallback((days: number) => {
    const selected = safeDate(period.end);
    if (!selected) return;
    selected.setDate(selected.getDate() + days);
    const date = toDateInput(selected);
    setPeriod({ start: date, end: date });
  }, [period.end, setPeriod]);

  const periodDays = useMemo(
    () => countSelectedPeriodDays(getSelectedPeriodRange(period)),
    [period]
  );

  const value = useMemo<PeriodContextValue>(
    () => ({
      period,
      periodDays,
      setPeriod,
      setPresetPeriod,
      setCurrentMonthPeriod,
      setMonthPeriod,
      setDayPeriod,
      shiftDayPeriod,
    }),
    [period, periodDays, setPeriod, setPresetPeriod, setCurrentMonthPeriod, setMonthPeriod, setDayPeriod, shiftDayPeriod]
  );

  return <PeriodContext.Provider value={value}>{children}</PeriodContext.Provider>;
}

export function useOptionalPeriod() {
  return useContext(PeriodContext);
}

export function usePeriod() {
  const ctx = useContext(PeriodContext);
  if (!ctx) {
    throw new Error("usePeriod precisa ser usado dentro de PeriodProvider.");
  }
  return ctx;
}

export type { Period };
