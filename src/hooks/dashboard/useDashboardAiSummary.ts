import { useCallback, useEffect, useMemo, useState } from "react";
import { getAiSummary } from "../../app/api";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

type Params = {
  period?: DashboardPeriod | null;
  resetKey: string;
};

export default function useDashboardAiSummary({ period, resetKey }: Params) {
  const safePeriod = useMemo(
    () => ensureDashboardPeriod(period),
    [period]
  );
  const [aiLoading, setAiLoading] = useState(false);
  const [aiErr, setAiErr] = useState<string | null>(null);
  const [aiReport, setAiReport] = useState<Record<string, unknown> | null>(null);

  const runAi = useCallback(async () => {
    setAiErr(null);
    setAiLoading(true);
    try {
      const report = await getAiSummary({ start: safePeriod.start, end: safePeriod.end });
      setAiReport(report);
    } catch (error: unknown) {
      setAiErr(errorMessage(error, "Erro na IA"));
    } finally {
      setAiLoading(false);
    }
  }, [safePeriod.end, safePeriod.start]);

  useEffect(() => {
    setAiErr(null);
    setAiReport(null);
  }, [resetKey, safePeriod.end, safePeriod.start]);

  return {
    aiLoading,
    aiErr,
    aiReport,
    runAi,
  };
}
