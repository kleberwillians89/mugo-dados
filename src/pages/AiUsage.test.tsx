// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getAiUsage: vi.fn() }));
vi.mock("../app/aiUsage", async (original) => ({ ...(await original<typeof import("../app/aiUsage")>()), ...api }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: unknown }) => children }));

import AiUsage from "./AiUsage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.clearAllMocks(); });

const bucket = (t: number, cost: number, extra = {}) => ({ calls: 2, errors: 0, input_tokens: t - 100, output_tokens: 100, total_tokens: t, cost_usd: cost, ...extra });
const report = (quota = false) => ({
  ok: true, period: { start: "2026-11-01", end: "2026-11-10" }, currency: "USD", estimated: true,
  totals: bucket(3000, 0.0032, { errors: quota ? 1 : 0 }),
  clients: [
    { client_id: "ruah", name: "Ruah Parfums", ...bucket(2000, 0.002), features: [{ feature: "studio_content_matrix", ...bucket(2000, 0.002) }], last_error: null, last_call: "2026-11-10T11:00:00Z" },
    { client_id: "roove", name: "Roove", ...bucket(1000, 0.0012), features: [], last_error: quota ? { code: "http_429:insufficient_quota", at: "2026-11-10T12:00:00Z", feature: "studio_content_matrix" } : null, last_call: "2026-11-10T12:00:00Z" },
  ],
  features: [{ feature: "studio_content_matrix", ...bucket(3000, 0.0032) }],
  daily: [{ date: "2026-11-10", ...bucket(3000, 0.0032) }],
  last_error: quota ? { code: "http_429:insufficient_quota", at: "2026-11-10T12:00:00Z", feature: "studio_content_matrix", client: "Roove" } : null,
  quota_exhausted: quota, unpriced_models: [],
});

describe("Consumo de IA", () => {
  it("mostra tokens e custo por cliente, do maior para o menor, com detalhe por recurso", async () => {
    api.getAiUsage.mockResolvedValue(report());
    await act(async () => root.render(<AiUsage />)); await act(async () => {});
    expect(api.getAiUsage).toHaveBeenCalledWith(expect.stringMatching(/^\d{4}-\d{2}-01$/), expect.any(String));
    const rows = [...host.querySelectorAll(".aiUsageTable tbody tr")].map((r) => r.textContent || "");
    expect(rows[0]).toContain("Ruah Parfums"); expect(rows[0]).toContain("2.000"); expect(rows[0]).toContain("66,7%");
    expect(rows[1]).toContain("Roove");
    await act(async () => { host.querySelector<HTMLButtonElement>(".aiUsageTable tbody th button")!.click(); });
    expect(host.textContent).toContain("Matriz de conteúdo");
    expect(host.textContent).toContain("Custo estimado");
  });

  it("avisa quando a OpenAI está sem crédito", async () => {
    api.getAiUsage.mockResolvedValue(report(true));
    await act(async () => root.render(<AiUsage />)); await act(async () => {});
    expect(host.querySelector(".aiUsageAlert")?.textContent).toContain("sem crédito");
    expect(host.textContent).toContain("Sem crédito na OpenAI");
  });

  it("troca o período", async () => {
    api.getAiUsage.mockResolvedValue(report());
    await act(async () => root.render(<AiUsage />)); await act(async () => {});
    const btn = [...host.querySelectorAll<HTMLButtonElement>('.ds-segmented button')].find((b) => b.textContent === "Últimos 7 dias")!;
    await act(async () => { btn.click(); }); await act(async () => {});
    expect(api.getAiUsage).toHaveBeenCalledTimes(2);
  });
});
