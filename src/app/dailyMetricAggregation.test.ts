import { describe, expect, it } from "vitest";
import type { DashboardDailyMetric } from "./DashboardDataContext";
import { aggregateMetaDays, civilDates } from "./dailyMetricAggregation";

const row = (date: string, spend: number, purchases: number, revenue: number) => ({
  metric_date: date, meta_spend: spend, meta_purchases: purchases, meta_attributed_revenue: revenue,
} as DashboardDailyMetric);

const known = [
  row("2026-06-01", 378.96, 1, 350.10),
  row("2026-06-03", 293.91, 0, 0),
  row("2026-06-11", 306.15, 4, 2172.27),
  row("2026-06-17", 216.92, 4, 1628.80),
  row("2026-06-29", 203.52, 3, 1887.91),
];

describe("aggregateMetaDays", () => {
  it("usa exatamente a linha canônica do dia", () => {
    expect(aggregateMetaDays(known.filter((item) => item.metric_date === "2026-06-11")))
      .toEqual({ spend: 306.15, purchases: 4, attributedRevenue: 2172.27 });
  });

  it("semana e mês são somas das linhas diárias, inclusive dia com zero compra", () => {
    const week = [row("2026-06-08", 100, 0, 0), known[2], row("2026-06-14", 200, 1, 300)];
    expect(aggregateMetaDays(week)).toEqual({ spend: 606.15, purchases: 5, attributedRevenue: 2472.27 });
    const knownByDate = new Map(known.map((item) => [item.metric_date, item]));
    const month = Array.from({ length: 30 }, (_, index) => {
      const date = `2026-06-${String(index + 1).padStart(2, "0")}`;
      return knownByDate.get(date) || row(date, 0, 0, 0);
    });
    month[29] = row("2026-06-30", 6131.23, 28, 15374.18);
    expect(month).toHaveLength(30);
    expect(aggregateMetaDays(month)).toEqual({ spend: 7530.69, purchases: 40, attributedRevenue: 21413.26 });
  });

  it("não converte ausência de coverage em zero", () => {
    expect(aggregateMetaDays([])).toEqual({ spend: null, purchases: null, attributedRevenue: null });
  });

  it("gera dias civis inclusivos sem deslocamento de fuso", () => {
    expect(civilDates("2026-06-29", "2026-07-02")).toEqual([
      "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02",
    ]);
  });
});
