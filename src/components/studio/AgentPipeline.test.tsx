// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ops = vi.hoisted(() => ({ getAgentRun: vi.fn(), startAgentRun: vi.fn(), continueAgentRun: vi.fn(), cancelAgentRun: vi.fn() }));
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
    expect(btn("Pôr na fila")).toBeTruthy();  // ocupada: novo pedido vai para a fila
  });

  it("para na Matriz e segue no Gerar conteúdo", async () => {
    const waiting = { id: "r1", status: "aguardando", created_at: "2026-11-11T18:00:00Z", matrix_id: "m1", item_ids: [], summary: "Matriz pronta.",
      error: null, finished_at: null, options: { weeks: 2 }, queued: 1,
      steps: [{ ...STEPS[0], status: "feito" }, { ...STEPS[1], status: "feito", detail: "8 pautas em 2 semanas" }] };
    ops.getAgentRun.mockResolvedValue({ run: waiting, steps: STEPS });
    ops.continueAgentRun.mockResolvedValue({ steps: STEPS, run: { ...waiting, status: "rodando", queued: undefined } });
    await act(async () => { root.render(<AgentPipeline clientId="roove" />); });
    expect(host.querySelector(".agentPause")?.textContent).toContain("Matriz pronta (2 semanas)");
    expect(host.textContent).toContain("1 pedido na fila");
    await act(async () => { btn("Gerar conteúdo").click(); });
    expect(ops.continueAgentRun).toHaveBeenCalledWith("r1");
    expect(host.querySelector(".agentPause")).toBeNull();
  });

  it("manda período e foco ao rodar", async () => {
    ops.getAgentRun.mockResolvedValue({ run: null, steps: STEPS });
    ops.startAgentRun.mockResolvedValue({ steps: STEPS, run: { id: "r1", status: "rodando", created_at: "x", matrix_id: null, item_ids: [], summary: null, error: null, finished_at: null, steps: [] } });
    await act(async () => { root.render(<AgentPipeline clientId="roove" />); });
    const select = host.querySelector('select[aria-label="Semanas da esteira"]') as HTMLSelectElement;
    const area = host.querySelector(".agentFocus textarea") as HTMLTextAreaElement;
    await act(async () => {
      const setValue = (el: HTMLElement, value: string) => {
        const proto = Object.getPrototypeOf(el);
        Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
        el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
      };
      setValue(select, "6"); setValue(area, "Natal");
    });
    await act(async () => { btn("Rodar esteira de agentes").click(); });
    expect(ops.startAgentRun).toHaveBeenCalledWith({ weeks: 6, focus: "Natal" });
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
