import { describe, expect, it } from "vitest";
import { previousDashboardPeriod } from "./period";

describe("previousDashboardPeriod — janela anterior de mesma duração, sem inventar histórico", () => {
  it("período de 8 dias (01-08 ago) compara contra os 8 dias imediatamente anteriores", () => {
    const previous = previousDashboardPeriod({ start: "2026-08-01", end: "2026-08-08" });
    expect(previous).toEqual({ start: "2026-07-24", end: "2026-07-31" });
  });

  it("período de 1 dia compara contra o dia anterior", () => {
    const previous = previousDashboardPeriod({ start: "2026-08-08", end: "2026-08-08" });
    expect(previous).toEqual({ start: "2026-08-07", end: "2026-08-07" });
  });

  it("respeita a virada de mês", () => {
    const previous = previousDashboardPeriod({ start: "2026-08-01", end: "2026-08-01" });
    expect(previous).toEqual({ start: "2026-07-31", end: "2026-07-31" });
  });
});
