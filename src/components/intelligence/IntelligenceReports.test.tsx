// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import type { IntelligenceAnalysisRecord } from "../../app/intelligenceTypes";
import { comparableReportMetric, printIntelligenceReport, reportPeriod, validReport } from "../../app/intelligenceReport";
import { generateIntelligenceAnalysis, getLatestIntelligenceAnalysis } from "../../app/api";
import IntelligenceReports from "./IntelligenceReports";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const active = vi.hoisted(() => ({ id: "tenant-a" }));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => active.id }));
vi.mock("../../app/api", () => ({ generateIntelligenceAnalysis: vi.fn(), getLatestIntelligenceAnalysis: vi.fn() }));
// Vitest stubs CSS imports; export tests need the actual authored print styles.
vi.mock("../../styles/intelligence-reports.css?raw", async () => {
  const { readFileSync } = await import("node:fs");
  return { default: readFileSync(process.cwd() + "/src/styles/intelligence-reports.css", "utf8") };
});
const period = { start: "2026-08-01", end: "2026-08-31" };
function record(dates = period, id = "tenant-a"): IntelligenceAnalysisRecord {
  return { id: "analysis", client_id: id, period_start: dates.start, period_end: dates.end, status: "completed",
    provider: "openai", model: "fixture", created_at: "2026-09-01T12:00:00Z", completed_at: "2026-09-01T12:00:00Z", error_code: null,
    sources: [{ id: "meta", label: "Canal A", status: "available", connected: true, covered_days: 31, data_points: 31, last_sync_at: null },
      { id: "google_ads", label: "Canal B", status: "partial", connected: true, covered_days: null, data_points: 1, last_sync_at: null },
      { id: "ga4", label: "Canal C", status: "error", connected: true, covered_days: null, data_points: 0, last_sync_at: null }],
    data_quality: { status: "partial", message: "Análise parcial: fontes com coberturas diferentes.", score: 50, total_sources: 3, available_sources: 2, errors: 1 },
    metrics_snapshot: [{ id: "spend", label: "Investimento", source: "meta", value: 100, previous_value: 90, variation_percent: 11, format: "currency", status: "confirmed" },
      { id: "partial", label: "Receita observada", source: "google_ads", value: 200, previous_value: 100, variation_percent: 100, format: "currency", status: "partial" },
      { id: "sessions", label: "Sessões", source: "ga4", value: null, previous_value: null, variation_percent: null, format: "integer", status: "error" }],
    analysis: { executive: { overall: "Diagnóstico validado da empresa.", main_change: "", opportunity: "", attention: "", priority_action: "Revisar distribuição." },
      insights: [{ title: "Revisar distribuição", category: "opportunity", interpretation: "Hipótese sustentada pelo indicador.", action: "Revisar a distribuição.", reason: "Evidência disponível.", metric_ids: ["spend"], sources: ["meta"], impact: "high", confidence: "medium" }],
      actions: [{ priority: "now", recommendation: "Revisar a distribuição.", justification: "Indicador observado.", sources: ["meta"], impact_expected: "Melhora a avaliar", confidence: "medium", metric_id: "spend" }] },
  };
}
function response(dates = period, id = "tenant-a") {
  return { ok: true, status: "completed", provider_configured: true, analysis: record(dates, id), snapshot: { client: { id, name: "Empresa exemplo" } } } as Awaited<ReturnType<typeof generateIntelligenceAnalysis>>;
}
let container: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  active.id = "tenant-a";
  vi.mocked(generateIntelligenceAnalysis).mockReset().mockImplementation(async dates => response(dates, active.id));
  vi.mocked(getLatestIntelligenceAnalysis).mockReset().mockResolvedValue({ ok: true, provider_configured: true, analysis: record() });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); });
async function render(configured = true) {
  await act(async () => { root.render(<IntelligenceReports key={active.id} clientId={active.id} clientName="Empresa exemplo" initialDate={period.start} providerConfigured={configured} />); });
}
function button(text: string) { return [...container.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === text)!; }
async function generate() { await act(async () => { container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); }); }

describe("Relatórios — períodos e métricas canônicas", () => {
  it("usa semana segunda/domingo, virada de ano e mês calendário inclusive bissexto", () => {
    expect(reportPeriod("weekly", "2027-01-01")).toEqual({ start: "2026-12-28", end: "2027-01-03" });
    expect(reportPeriod("monthly", "2024-02-18")).toEqual({ start: "2024-02-01", end: "2024-02-29" });
    expect(reportPeriod("monthly", "2026-12-08")).toEqual({ start: "2026-12-01", end: "2026-12-31" });
    for (const value of ["", "2026-02-30", "texto livre"]) expect(() => reportPeriod("weekly", value)).toThrow();
  });
  it("recusa relatório de outro tenant, outro período, incompleto ou sem análise", () => {
    expect(validReport(record(), "tenant-a", period)).toBe(true);
    expect(validReport(record(), "tenant-b", period)).toBe(false);
    expect(validReport(record(), "tenant-a", { ...period, end: "2026-08-30" })).toBe(false);
    expect(validReport({ ...record(), status: "failed" }, "tenant-a", period)).toBe(false);
    expect(validReport({ ...record(), analysis: null }, "tenant-a", period)).toBe(false);
  });
  it("exibe comparação somente com valor anterior, variação e indicador confirmado", () => {
    const metric = record().metrics_snapshot[0];
    expect(comparableReportMetric(metric)).toBe(true);
    for (const changed of [{ previous_value: null }, { variation_percent: null }, { value: null }, { status: "partial" as const }]) {
      expect(comparableReportMetric({ ...metric, ...changed })).toBe(false);
    }
  });
});

describe("Relatórios — fluxo autorizado existente e estados", () => {
  it("não chama APIs ao abrir e gera apenas após ação explícita com intervalo mensal", async () => {
    await render(); expect(generateIntelligenceAnalysis).not.toHaveBeenCalled(); expect(getLatestIntelligenceAnalysis).not.toHaveBeenCalled();
    await generate();
    expect(generateIntelligenceAnalysis).toHaveBeenCalledWith(period, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(container.querySelector(".mugoReportExecutive")?.textContent).toContain("Diagnóstico validado");
    expect(container.querySelectorAll(".mugoReportAction")).toHaveLength(1);
    expect(button("Exportar PDF")).toBeDefined();
  });
  it("seleção semanal usa intervalo calculado sem mudar a empresa", async () => {
    await render(); await act(async () => {
      const select = container.querySelector("select")!; select.value = "weekly"; select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await generate();
    expect(vi.mocked(generateIntelligenceAnalysis).mock.calls[0][0]).toEqual({ start: "2026-07-27", end: "2026-08-02" });
    expect(container.querySelector(".mugoReportHeader")?.textContent).toContain("Relatório Semanal");
  });
  it("identifica parcial, indisponível e cobertura desconhecida sem transformar ausência em zero", async () => {
    await render(); await generate();
    const preview = container.querySelector(".mugoReport")!;
    expect(preview.textContent).toContain("Relatório com dados parciais");
    expect(preview.textContent).toContain("Cobertura parcial"); expect(preview.textContent).toContain("Falha na leitura");
    expect(preview.textContent).toContain("Sem cobertura temporal confirmada");
    expect(preview.querySelectorAll(".mugoReportKpis>div")[2].textContent).toContain("Erro na consulta");
    expect(preview.querySelectorAll(".mugoReportKpis>div")[1].textContent).not.toContain("100% vs.");
  });
  it("impede solicitações duplicadas e mostra processamento", async () => {
    let finish!: (value: Awaited<ReturnType<typeof generateIntelligenceAnalysis>>) => void;
    vi.mocked(generateIntelligenceAnalysis).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    await render(); await generate(); await generate();
    expect(generateIntelligenceAnalysis).toHaveBeenCalledTimes(1);
    expect(button("Gerando relatório…").disabled).toBe(true);
    expect(container.textContent).toContain("validando as evidências");
    await act(async () => finish(response()));
  });
  it("preserva relatório anterior em falha e não expõe o erro bruto", async () => {
    await render(); await generate();
    vi.mocked(generateIntelligenceAnalysis).mockRejectedValueOnce(new Error("private-fixture"));
    await generate();
    expect(container.querySelector(".mugoReportExecutive")?.textContent).toContain("Diagnóstico validado");
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("preservado");
    expect(container.textContent).not.toContain("private-fixture");
  });
  it("carrega análise salva sem IA mesmo quando geração está desabilitada", async () => {
    await render(false); expect(button("Gerar relatório com IA").disabled).toBe(true);
    await act(async () => button("Ver análise salva deste período").click());
    expect(getLatestIntelligenceAnalysis).toHaveBeenCalledWith(period, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(generateIntelligenceAnalysis).not.toHaveBeenCalled(); expect(container.querySelector(".mugoReport")).not.toBeNull();
  });
  it("trata ausência de análise salva sem inventar conteúdo", async () => {
    vi.mocked(getLatestIntelligenceAnalysis).mockResolvedValueOnce({ ok: true, provider_configured: true, analysis: null });
    await render(); await act(async () => button("Ver análise salva deste período").click());
    expect(container.textContent).toContain("Não há análise válida salva");
    expect(container.querySelector(".mugoReport")).toBeNull(); expect(generateIntelligenceAnalysis).not.toHaveBeenCalled();
  });
  it("rejeita resposta de outro tenant ou intervalo antes de exibir/exportar", async () => {
    await render();
    for (const invalid of [response(period, "tenant-b"), response({ ...period, end: "2026-08-30" }),
      { ...response(), snapshot: { ...response().snapshot, client: { id: "tenant-b", name: "Outra empresa" } } }]) {
      vi.mocked(generateIntelligenceAnalysis).mockResolvedValueOnce(invalid); await generate();
      expect(container.querySelector(".mugoReport")).toBeNull(); expect(button("Exportar PDF")).toBeUndefined();
    }
  });
  it("troca de empresa aborta chamada e descarta resposta atrasada", async () => {
    let finish!: (value: Awaited<ReturnType<typeof generateIntelligenceAnalysis>>) => void;
    vi.mocked(generateIntelligenceAnalysis).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    await render(); await generate(); const signal = vi.mocked(generateIntelligenceAnalysis).mock.calls[0][1]!.signal;
    active.id = "tenant-b"; await render(); expect(signal?.aborted).toBe(true);
    await act(async () => finish(response(period, "tenant-a")));
    expect(container.querySelector(".mugoReport")).toBeNull();
  });
});

describe("Relatórios — exportação sem IA e sem HTML injetado", () => {
  it("exporta somente a prévia com identidade, empresa, período e CSS A4", async () => {
    await render(); await generate();
    const doc = document.implementation.createHTMLDocument();
    const popup = { document: doc, opener: window, focus: vi.fn(), print: vi.fn(), close: vi.fn(), addEventListener: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    const calls = vi.mocked(generateIntelligenceAnalysis).mock.calls.length;
    await act(async () => button("Exportar PDF").click());
    expect(popup.opener).toBeNull(); expect(popup.print).toHaveBeenCalledTimes(1);
    expect(doc.body.textContent).toContain("Mugô"); expect(doc.body.textContent).toContain("Empresa exemplo");
    expect(doc.body.textContent).toContain("01/08/2026 — 31/08/2026"); expect(doc.body.textContent).toContain("Diagnóstico validado");
    expect(doc.querySelector("style")?.textContent).toContain("size:A4"); expect(doc.querySelector("form,button")).toBeNull();
    expect(generateIntelligenceAnalysis).toHaveBeenCalledTimes(calls);
    popup.addEventListener.mock.calls[0][1](); expect(popup.close).toHaveBeenCalledTimes(1);
  });
  it("mantém texto potencialmente malicioso como texto e trata bloqueio de popup", async () => {
    const node = document.createElement("article"); node.textContent = '<script>alert("fixture")</script>';
    const doc = document.implementation.createHTMLDocument();
    const popup = { document: doc, opener: window, focus: vi.fn(), print: vi.fn(), close: vi.fn(), addEventListener: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    printIntelligenceReport(node, '<img src=x onerror="fixture">', "@page{size:A4}");
    expect(doc.querySelector("script,img")).toBeNull(); expect(doc.body.textContent).toBe(node.textContent);
    await render(); await generate(); vi.mocked(window.open).mockReturnValue(null);
    await act(async () => button("Exportar PDF").click());
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Salvar como PDF");
    expect(container.querySelector(".mugoReport")).not.toBeNull();
  });
});


describe("Relatórios — insuficiência e prioridades", () => {
  it("não fabrica relatório quando o pipeline recusa dados insuficientes", async () => {
    vi.mocked(generateIntelligenceAnalysis).mockRejectedValueOnce(new Error("AI_INSUFFICIENT_DATA"));
    await render(); await generate();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("dados suficientes");
    expect(container.querySelector(".mugoReport")).toBeNull();
  });
  it("mostra ausência de ações e limita a três prioridades realmente existentes", async () => {
    const result = response(); result.analysis.analysis!.actions = []; result.analysis.analysis!.insights = [];
    vi.mocked(generateIntelligenceAnalysis).mockResolvedValueOnce(result);
    await render(); await generate();
    expect(container.querySelector(".mugoReport")?.textContent).toContain("Não há ações prioritárias com evidências suficientes");
    const action = record().analysis!.actions[0];
    result.analysis.analysis!.actions = ["monitor", "week", "now", "investigate"].map(priority => ({ ...action, priority: priority as typeof action.priority, recommendation: priority }));
    vi.mocked(generateIntelligenceAnalysis).mockResolvedValueOnce(result); await generate();
    expect([...container.querySelectorAll(".mugoReportAction h4")].map(item => item.textContent)).toEqual(["now", "week", "monitor"]);
  });
});
