// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ops = vi.hoisted(() => ({ getAgentRun: vi.fn(), startAgentRun: vi.fn() }));
vi.mock("../../app/contentOps", async (original) => ({ ...(await original<typeof import("../../app/contentOps")>()), ...ops }));
const studio = vi.hoisted(() => ({ applySuggestion: vi.fn(), dismissSuggestion: vi.fn(), requestSuggestion: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));

import AgentPipeline from "./AgentPipeline";
import AiSuggestionCard from "./AiSuggestionCard";

const STEPS = [{ key: "pesquisa", agent: "Pesquisador", task: "Lê os dados" }, { key: "estrategia", agent: "Estrategista", task: "Monta a matriz" }];
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement;

describe("Esteira de agentes", () => {
  it("roda e mostra cada agente com o andamento", async () => {
    ops.getAgentRun.mockResolvedValue({ run: null, steps: STEPS });
    ops.startAgentRun.mockResolvedValue({ steps: STEPS, run: { id: "r1", status: "rodando", created_at: "2026-11-11T18:00:00Z", matrix_id: null, item_ids: [],
      summary: null, error: null, finished_at: null,
      steps: [{ ...STEPS[0], status: "feito", detail: "40 posts analisados" }, { ...STEPS[1], status: "rodando", detail: null }] } });
    await act(async () => { root.render(<AgentPipeline clientId="roove" />); });
    await act(async () => { btn("Rodar esteira de agentes").click(); });
    expect(ops.startAgentRun).toHaveBeenCalled();
    expect(host.querySelector(".agentSteps li.is-feito")?.textContent).toContain("40 posts analisados");
    expect(host.querySelector(".agentSteps li.is-rodando")?.textContent).toContain("Estrategista");
    expect(btn("Rodando…").disabled).toBe(true);
  });

  it("execução concluída mostra o resumo", async () => {
    ops.getAgentRun.mockResolvedValue({ steps: STEPS, run: { id: "r1", status: "concluida", created_at: "2026-11-11T18:00:00Z", matrix_id: "m1", item_ids: ["i1"],
      summary: "12 posts prontos para a revisão interna.", error: null, finished_at: "2026-11-11T18:06:00Z", steps: STEPS.map((s) => ({ ...s, status: "feito" })) } });
    await act(async () => { root.render(<AgentPipeline clientId="roove" />); });
    await act(async () => { btn("Ver última execução").click(); });
    expect(host.textContent).toContain("12 posts prontos para a revisão interna.");
  });
});

describe("Sugestão da IA para o ajuste", () => {
  const item = { id: "i1", status: "rejeitado", title: "Reels", review_note: "Mais curto",
    ai_suggestion: { hook: "Novo gancho", caption_draft: "Legenda curta", script: null, visual_idea: "Close no produto", summary: "Encurtei", note: "Mais curto", created_at: "x" } } as never;

  it("aplica no post e devolve o post atualizado", async () => {
    const onItemChange = vi.fn();
    studio.applySuggestion.mockResolvedValue({ item: { id: "i1", hook: "Novo gancho", ai_suggestion: null } });
    await act(async () => { root.render(<AiSuggestionCard item={item} onItemChange={onItemChange} />); });
    expect(host.textContent).toContain("Pedido do cliente: “Mais curto”");
    expect(host.textContent).toContain("Close no produto");
    await act(async () => { btn("Aplicar no post").click(); });
    expect(studio.applySuggestion).toHaveBeenCalledWith("i1");
    expect(onItemChange).toHaveBeenCalledWith({ id: "i1", hook: "Novo gancho", ai_suggestion: null });
  });

  it("ajuste sem sugestão ainda: equipe pede à IA", async () => {
    const onItemChange = vi.fn();
    studio.requestSuggestion.mockResolvedValue({ suggestion: { hook: "G", caption_draft: null, script: null, visual_idea: null, summary: null, note: "x", created_at: "x" } });
    await act(async () => { root.render(<AiSuggestionCard item={{ id: "i1", status: "rejeitado", ai_suggestion: null } as never} onItemChange={onItemChange} />); });
    await act(async () => { btn("Pedir sugestão à IA").click(); });
    expect(studio.requestSuggestion).toHaveBeenCalledWith("i1");
    expect(onItemChange.mock.calls[0][0].ai_suggestion.hook).toBe("G");
  });
});
