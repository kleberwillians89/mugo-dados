// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { clearDashboardCacheByPrefix } from "../../hooks/dashboard/cache";
import { PeriodProvider, usePeriod } from "../../app/PeriodContext";
import { DashboardDataProvider, useDashboardSnapshot } from "../../app/DashboardDataContext";
import PeriodSelector from "./PeriodSelector";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const mock = vi.hoisted(() => ({ calls: [] as { table: string; tenant: string; start: string; end: string; offset: number }[], campaigns: 0 }));
vi.mock("../../app/supabase", () => ({ supabase: { from: (table: string) => {
  const values = { table, tenant: "", start: "", end: "", offset: 0, last: 999 };
  const builder = {
    select: () => builder,
    eq: (_column: string, value: string) => { values.tenant = value; return builder; },
    gte: (_column: string, value: string) => { values.start = value; return builder; },
    lte: (_column: string, value: string) => { values.end = value; return builder; },
    order: () => builder,
    range: (offset: number, last: number) => { values.offset = offset; values.last = last; return builder; },
    then: (resolve: (value: unknown) => void) => {
      mock.calls.push({ ...values });
      const rows: Record<string, unknown>[] = [];
      if (table === "dashboard_daily_metrics") {
        for (const date = new Date(`${values.start}T12:00:00Z`); date.toISOString().slice(0, 10) <= values.end; date.setUTCDate(date.getUTCDate() + 1)) {
          rows.push({ client_id: values.tenant, metric_date: date.toISOString().slice(0, 10), meta_spend: 10 });
        }
      }
      if (table === "dashboard_campaign_metrics") for (let index = 0; index < mock.campaigns; index++) rows.push({ client_id: values.tenant, metric_date: values.start, provider: "meta", campaign_id: String(index) });
      resolve({ data: rows.slice(values.offset, values.last + 1), error: null });
    },
  };
  return builder;
} } }));
let root: Root;
let node: HTMLDivElement;
function Result() {
  const { period } = usePeriod();
  const state = useDashboardSnapshot(period.start, period.end);
  return <output>{period.start}:{period.end}:{state.daily.reduce((sum, row) => sum + Number(row.meta_spend), 0)}:{state.campaigns.length}</output>;
}
function App({ tenant = "tenant-a" }: { tenant?: string }) {
  return <PeriodProvider><DashboardDataProvider clientId={tenant} enabled tenantReady><PeriodSelector /><Result /></DashboardDataProvider></PeriodProvider>;
}
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-05T15:00:00Z"));
  const stored = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => stored.get(key) ?? null, setItem: (key: string, value: string) => stored.set(key, value), clear: () => stored.clear() });
  clearDashboardCacheByPrefix("read-model-period-v3"); sessionStorage.clear(); mock.calls.length = 0; mock.campaigns = 0;
  localStorage.setItem("mugo.period", JSON.stringify({ start: "2026-09-06", end: "2026-10-05" }));
  node = document.createElement("div"); root = createRoot(node);
});
afterEach(() => { act(() => root.unmount()); vi.useRealTimers(); });
async function click(label: string) {
  const button = [...node.querySelectorAll("button")].find(button => button.textContent === label);
  expect(button).toBeTruthy(); await act(async () => button!.click());
}
function assertQueries(start: string, end: string, count: number) {
  const dated = mock.calls.filter(call => call.table !== "dashboard_source_snapshots");
  expect(dated.slice(-3).every(call => call.start === start && call.end === end && call.tenant === "tenant-a")).toBe(true);
  expect(node.querySelector("output")?.textContent).toBe(`${start}:${end}:${count * 10}:0`);
}
test("90 dias muda limites reais da consulta; 7/30 consultam somente seus subconjuntos", async () => {
  await act(async () => root.render(<App />)); assertQueries("2026-09-06", "2026-10-05", 30);
  await click("90 dias"); assertQueries("2026-07-08", "2026-10-05", 90);
  await click("7 dias"); assertQueries("2026-09-29", "2026-10-05", 7);
  await click("30 dias"); expect(node.querySelector("output")?.textContent).toBe("2026-09-06:2026-10-05:300:0");
  expect(mock.calls).toHaveLength(12); // volta a 30 usa cache da mesma janela/tenant.
});
test("mês anterior e atual alteram consultas reais", async () => {
  await act(async () => root.render(<App />));
  await click("Mês anterior"); assertQueries("2026-09-01", "2026-09-30", 30);
  await click("Mês atual"); assertQueries("2026-10-01", "2026-10-05", 5);
});
async function fill(label: string, value: string) {
  const input = [...node.querySelectorAll("label")].find(item => item.textContent === label)?.querySelector("input");
  expect(input).toBeTruthy();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input!.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
test("personalizado consulta intervalo informado, sem carregar 90 dias", async () => {
  await act(async () => root.render(<App />)); await click("Personalizado");
  await fill("Início", "2026-08-01"); await fill("Fim", "2026-08-10"); await click("Aplicar período");
  assertQueries("2026-08-01", "2026-08-10", 10);
});
test("personalizado acima de 90 dias é rejeitado antes da consulta", async () => {
  await act(async () => root.render(<App />)); await click("Personalizado");
  await fill("Início", "2026-01-01"); await click("Aplicar período");
  expect(node.querySelector('[role="alert"]')?.textContent).toBe("Selecione um período de 1 a 90 dias.");
  expect(mock.calls).toHaveLength(4);
});
test("paginação do read model mantém campanhas além de mil sem truncar", async () => {
  mock.campaigns = 1101; await act(async () => root.render(<App />));
  expect(node.querySelector("output")?.textContent).toContain(":1101");
  expect(mock.calls.filter(call => call.table === "dashboard_campaign_metrics").map(call => call.offset)).toEqual([0, 1000]);
});
test("trocar tenant não reutiliza cache de fatos de outro tenant", async () => {
  await act(async () => root.render(<App />)); mock.calls.length = 0;
  await act(async () => root.render(<App tenant="tenant-b" />));
  expect(mock.calls).toHaveLength(4);
  expect(mock.calls.every(call => call.tenant === "tenant-b")).toBe(true);
});
