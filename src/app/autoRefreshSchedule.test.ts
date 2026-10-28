import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { AUTO_REFRESH_SCHEDULES, nextAutoRefresh, nextAutoRefreshLabel } from "./autoRefreshSchedule";

describe("agenda das atualizações automáticas", () => {
  it("calcula a próxima rodada em horário de Brasília", () => {
    const now = new Date("2026-10-27T21:34:00Z"); // 18:34 em SP
    expect(nextAutoRefreshLabel("meta_ads", now)).toBe("próxima atualização automática por volta das 19:05");
    expect(nextAutoRefreshLabel("instagram", now)).toBe("próxima atualização automática por volta das 20:10");
    expect(nextAutoRefreshLabel("ga4", now)).toBe("próxima atualização automática por volta das 21:20");
    expect(nextAutoRefreshLabel("google_ads", now)).toBe("próxima atualização automática por volta das 18:35");
    expect(nextAutoRefreshLabel("fbits_official", now)).toBe("próxima atualização automática por volta das 19:00");
    expect(nextAutoRefreshLabel("shopify", now)).toBe("próxima atualização automática por volta das 18:45");
  });

  it("avisa quando a próxima é no dia seguinte", () => {
    expect(nextAutoRefreshLabel("instagram", new Date("2026-10-27T23:30:00Z"))).toBe("próxima atualização automática amanhã por volta das 03:10");
  });

  it("fonte sem agenda não mostra nada", () => {
    expect(nextAutoRefresh("desconhecida")).toBeNull();
    expect(nextAutoRefreshLabel("desconhecida")).toBeNull();
  });

  it("segue exatamente os horários da agenda do despachante", () => {
    const dispatcher = readFileSync(new URL("../../server/services/job_dispatcher.py", import.meta.url), "utf8");
    const crons = [...dispatcher.matchAll(/ScheduledJob\("([^"]+)"/g)].map((m) => m[1]);
    for (const expected of ["5 * * * *", "10 6,12,18,23 * * *", "20 */3 * * *", "35 */3 * * *", "0,30 * * * *", "15,45 * * * *"]) {
      expect(crons).toContain(expected);
    }
    expect(Object.keys(AUTO_REFRESH_SCHEDULES)).toEqual(expect.arrayContaining(["meta_ads", "instagram", "ga4", "google_ads", "fbits", "shopify"]));
  });
});
