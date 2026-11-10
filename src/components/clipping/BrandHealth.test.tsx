// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { writeFileSync } from "node:fs";

const split = (p: number, n: number, m: number, g: number, s = 0) => ({ positivo: p, neutro: n, misto: m, negativo: g, sem_analise: s });
const weeks = ["2026-08-10", "2026-08-17", "2026-08-24", "2026-08-31", "2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02", "2026-11-09"];
const P = [30, 34, 31, 40, 38, 44, 47, 45, 52, 74, 63, 66, 71, 48], N = [30, 28, 33, 35, 34, 36, 38, 40, 39, 39, 42, 44, 46, 32];
const G = [4, 5, 4, 6, 5, 4, 6, 5, 7, 21, 9, 6, 5, 5];
const fixture = {
  period: { start: "2026-08-11", end: "2026-11-10", grain: "week", previous_start: "2026-05-11", previous_end: "2026-08-10" },
  sources: ["news", "comments", "direct"],
  kpis: { index: 74, index_previous: 68, index_label: "Saudável", mentions: 1284, mentions_previous: 1044, mentions_change: 23, net: 38, net_previous: 34,
    negative: 96, negative_share: 7.5, negative_share_previous: 6.3, unanalyzed: 12, alerts_open: 2, alerts_high: 1 },
  split: split(586, 548, 54, 96, 12),
  series: weeks.map((bucket, i) => { const s = split(P[i], N[i], 3, G[i], i === 13 ? 6 : 0); return { bucket, ...s, total: P[i] + N[i] + 3 + G[i] + (i === 13 ? 6 : 0), net: Math.round((P[i] - G[i]) / (P[i] + N[i] + 3 + G[i]) * 100) }; }),
  channels: [{ source: "news", mentions: 71, previous: 74, change: -4.1, split: split(21, 39, 6, 5) },
    { source: "comments", mentions: 842, previous: 643, change: 31, split: split(438, 320, 25, 59) },
    { source: "direct", mentions: 371, previous: 331, change: 12, split: split(127, 189, 23, 32, 12) }],
  themes: [{ theme: "decant / tamanhos", mentions: 212, previous: 143, change: 48, tone: "positivo" },
    { theme: "black friday", mentions: 131, previous: 42, change: 212, tone: "positivo" },
    { theme: "prazo de entrega", mentions: 64, previous: 37, change: 73, tone: "negativo" }],
  alerts: [{ id: "a1", kind: "termo", term: "não chegou", severity: "alto", mentions: 9, sources: ["comments"], sample: "meu pedido não chegou", detail: "9 menções em 48 h", status: "aberto", first_seen_at: "2026-11-09T10:00:00Z", last_seen_at: "2026-11-10T10:00:00Z", resolved_at: null }],
};

vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "ruah" }));
const getBrandHealth = vi.fn(async () => fixture);
const analyzeBrandHealth = vi.fn(async () => ({ classified: 40, failed: 0, news_analyzed: 36, news_pending: 84, alerts_opened: 0 }));
vi.mock("../../app/brandHealth", async (orig) => ({ ...(await orig<typeof import("../../app/brandHealth")>()), getBrandHealth: (q: unknown) => getBrandHealth(q),
  analyzeBrandHealth: () => analyzeBrandHealth() }));

import BrandHealth from "./BrandHealth";
import { presetRange, bucketLabel } from "../../app/brandHealth";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("Saúde da marca", () => {
  it("presets e rótulos de período", () => {
    const today = new Date(2026, 10, 10);
    expect(presetRange("7d", today)).toEqual({ start: "2026-11-04", end: "2026-11-10" });
    expect(presetRange("quarter", today)).toEqual({ start: "2026-10-01", end: "2026-11-10" });
    expect(presetRange("year", today).start).toBe("2026-01-01");
    expect(bucketLabel("2026-10-01", "quarter")).toBe("4º tri 2026");
    expect(bucketLabel("2026-11-09", "week", true)).toBe("Semana de 09/11");
  });

  it("mostra números, gráficos, canais, assuntos e alertas; troca o agrupamento", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => root.render(<BrandHealth canManage onOpenAlerts={() => undefined} />));
    const text = container.textContent || "";
    expect(text).toContain("74/100");
    expect(text).toContain("1.284");
    expect(text).toContain("Saudável");
    expect(text).toContain("prazo de entrega");
    expect(text).toContain("“não chegou” — 9 menções");
    expect(container.querySelectorAll(".bhFill").length).toBeGreaterThan(40);
    if (process.env.BH_SNAPSHOT) writeFileSync(process.env.BH_SNAPSHOT, container.innerHTML);
    const month = [...container.querySelectorAll(".bhSeg button")].find((b) => b.textContent === "Mês") as HTMLButtonElement;
    await act(async () => month.click());
    expect(getBrandHealth).toHaveBeenLastCalledWith(expect.objectContaining({ grain: "month" }));
    root.unmount();
  });

  it("equipe analisa na hora o que ficou sem análise e a tela recarrega", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => root.render(<BrandHealth canManage />));
    const calls = getBrandHealth.mock.calls.length;
    const button = [...container.querySelectorAll("button")].find((b) => b.textContent === "Analisar agora") as HTMLButtonElement;
    expect(container.textContent).toContain("12 menções ainda sem análise");
    await act(async () => button.click());
    expect(analyzeBrandHealth).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Faltam 84 matérias");
    expect(getBrandHealth.mock.calls.length).toBeGreaterThan(calls);
    root.unmount();
  });

  it("cliente não vê alertas", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => root.render(<BrandHealth canManage={false} />));
    expect(container.textContent).not.toContain("Alertas de termos sensíveis");
    expect(container.textContent).toContain("Analisadas pela IA");
    expect(container.textContent).not.toContain("Analisar agora");
    root.unmount();
  });
});
