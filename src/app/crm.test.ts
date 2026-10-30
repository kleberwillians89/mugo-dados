import { describe, expect, it } from "vitest";
import { dueInfo, samePhone, windowOpen } from "./crm";
import { getAppRouteFromPath, getPathForRoute } from "./routes";

describe("crm helpers", () => {
  const today = new Date(2026, 9, 30, 15, 0);
  it("labels due dates relative to the local day", () => {
    expect(dueInfo("2026-10-30", today)).toEqual({ label: "Hoje", late: false });
    expect(dueInfo("2026-10-31", today)).toEqual({ label: "Amanhã", late: false });
    expect(dueInfo("2026-10-29", today)).toEqual({ label: "Ontem", late: true });
    expect(dueInfo(null, today)).toEqual({ label: "Sem prazo", late: false });
  });
  it("knows when the 24h window is open", () => {
    expect(windowOpen("2026-10-30T20:00:00Z", new Date("2026-10-30T19:00:00Z"))).toBe(true);
    expect(windowOpen("2026-10-30T18:00:00Z", new Date("2026-10-30T19:00:00Z"))).toBe(false);
    expect(windowOpen(null)).toBe(false);
  });
  it("matches the same phone with or without the 9th digit", () => {
    expect(samePhone("5511993161161", "551193161161")).toBe(true);
    expect(samePhone("+55 11 99316-1161", "5511993161161")).toBe(true);
    expect(samePhone("34632881089", "34632881089")).toBe(true);
    expect(samePhone("5511993161161", "5511993161162")).toBe(false);
    expect(samePhone(null, "5511993161161")).toBe(false);
  });
  it("routes /tarefas and /atendimento", () => {
    expect(getAppRouteFromPath("/tarefas")).toBe("tasks");
    expect(getAppRouteFromPath("/atendimento")).toBe("approval");
    expect(getPathForRoute("tasks")).toBe("/tarefas");
  });
});
