// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ listProjects: vi.fn(), createProject: vi.fn(), updateProject: vi.fn(), deleteProject: vi.fn(),
  generateProject: vi.fn(), chatProject: vi.fn(), projectToBrief: vi.fn() }));
vi.mock("../app/projects", async (original) => ({ ...(await original<typeof import("../app/projects")>()), ...api }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "ruah", getActiveClientName: () => "Ruah" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ controls }: { controls?: React.ReactNode }) => <div>{controls}</div> }));

import ProjectsPage from "./ProjectsPage";

const BASE = { id: "p1", kind: "evento", title: "Lançamento na loja", status: "fila", format: "Evento / Ativação", target_date: "2026-12-10",
  inputs: { idea: "Ativação com degustação" }, plan: {}, chat: [], created_at: "x", updated_at: "x" };
const PLAN = { summary: "Ativação para 80 convidados.", timeline: [{ date: "2026-11-20", phase: "Pré", task: "Fechar buffet" }],
  staff: [{ role: "Fotógrafo", qty: 2, note: "" }], budget: [{ category: "equipe", item: "Fotógrafo", value: 1500 }, { category: "locacao", item: "Tenda", value: 800 }],
  budget_total: 2300, risks: [{ risk: "Chuva", impact: "alto", mitigation: "Tenda" }], checklist: ["Bateria extra"] };

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.startsWith(label)) as HTMLButtonElement;
const show = async (kind: "planejamento" | "evento") => { await act(async () => { root.render(<ProjectsPage kind={kind} />); }); await act(async () => {}); };
const type = async (el: HTMLInputElement | HTMLTextAreaElement, value: string) => act(async () => {
  Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value")!.set!.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
});

describe("Evento", () => {
  it("cria, a IA gera o plano, edita o orçamento e manda para o Briefing", async () => {
    api.listProjects.mockResolvedValue({ projects: [], formats: ["Evento / Ativação", "Podcast"] });
    api.createProject.mockResolvedValue({ project: BASE });
    api.generateProject.mockResolvedValue({ project: { ...BASE, status: "em_andamento", plan: PLAN } });
    api.updateProject.mockImplementation(async (_k, _id, patch) => ({ project: { ...BASE, status: "em_andamento", plan: { ...PLAN, ...patch.plan, budget_total: 1500 } } }));
    api.projectToBrief.mockResolvedValue({ brief: { id: "b9" } });
    await show("evento");
    await act(async () => { btn("Nova produção").click(); });
    await type(host.querySelector(".projNew input") as HTMLInputElement, "Lançamento na loja");
    await act(async () => { btn("Gerar plano de produção").click(); });
    expect(api.createProject).toHaveBeenCalledWith("evento", { title: "Lançamento na loja", format: undefined, target_date: undefined, inputs: {} });
    expect(api.generateProject).toHaveBeenCalledWith("evento", "p1");
    expect(host.querySelector('.projCol[aria-label="Em andamento"]')?.textContent).toContain("Lançamento na loja");
    expect(host.textContent).toContain("Fechar buffet");
    await act(async () => { btn("Orçamento").click(); });
    expect(host.querySelector(".projBudgetTotal b")?.textContent).toContain("2.300");
    await act(async () => { btn("Tirar").click(); });
    await act(async () => { btn("Salvar orçamento").click(); });
    expect(api.updateProject.mock.calls[0][2].plan.budget).toEqual([{ category: "locacao", item: "Tenda", value: 800 }]);
    await act(async () => { btn("Mandar para o Briefing").click(); });
    expect(api.projectToBrief).toHaveBeenCalledWith("evento", "p1");
    expect(host.textContent).toContain("Já está no Briefing");
  });
});

describe("Planejamento", () => {
  it("copiloto responde e a conversa vira plano", async () => {
    const plan = { big_idea: "Presente que chega a tempo", strategy: "Urgência de entrega", kpis: [{ kpi: "Vendas", target: "300 kits" }], risks: ["Estoque"] };
    const proj = { ...BASE, kind: "planejamento", status: "em_andamento", format: null, inputs: { objective: "Vender kits" }, plan };
    api.listProjects.mockResolvedValue({ projects: [proj], formats: [] });
    api.chatProject.mockResolvedValue({ project: { ...proj, chat: [{ role: "equipe", content: "E o frete?", at: "x" }, { role: "copiloto", content: "Frete grátis acima de R$ 199.", at: "x" }] } });
    api.generateProject.mockResolvedValue({ project: { ...proj, plan: { ...plan, big_idea: "Frete grátis no presente" } } });
    await show("planejamento");
    await act(async () => { (host.querySelector(".projCard") as HTMLButtonElement).click(); });
    expect(host.querySelector(".projBigIdea")?.textContent).toContain("Presente que chega a tempo");
    expect(host.querySelector(".projKpis")?.textContent).toContain("300 kits");
    await type(host.querySelector(".projCopilot textarea") as HTMLTextAreaElement, "E o frete?");
    await act(async () => { btn("Enviar").click(); });
    expect(api.chatProject).toHaveBeenCalledWith("planejamento", "p1", "E o frete?");
    expect(host.textContent).toContain("Frete grátis acima de R$ 199.");
    await act(async () => { btn("Aplicar a conversa no plano").click(); });
    expect(api.generateProject).toHaveBeenCalledWith("planejamento", "p1", { use_chat: true, instruction: undefined });
    expect(host.querySelector(".projBigIdea")?.textContent).toContain("Frete grátis no presente");
  });
});
