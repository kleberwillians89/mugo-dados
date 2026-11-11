// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ listProjects: vi.fn(), createProject: vi.fn(), updateProject: vi.fn(), deleteProject: vi.fn(),
  generateProject: vi.fn(), chatProject: vi.fn(), projectToBrief: vi.fn(), refreshEventRadar: vi.fn(),
  listSuppliers: vi.fn(), createSupplier: vi.fn(), updateSupplier: vi.fn(), deleteSupplier: vi.fn(),
  listEventSuppliers: vi.fn(), linkEventSupplier: vi.fn(), updateEventSupplier: vi.fn(), unlinkEventSupplier: vi.fn(), eventSuppliersToBudget: vi.fn() }));
vi.mock("../../app/projects", async (original) => ({ ...(await original<typeof import("../../app/projects")>()), ...api }));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "ruah", getActiveClientName: () => "Ruah" }));
vi.mock("../Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../data/PageHeader", () => ({ default: ({ controls }: { controls?: React.ReactNode }) => <div>{controls}</div> }));

import ProjectsPage from "../../pages/ProjectsPage";

const CATS = { buffet: "Buffet e alimentação", fotografia: "Fotografia", outros: "Outros" };
const SUPPLIERS = [{ id: "s1", name: "Buffet Sabor", category: "buffet", city: "São Paulo", price_note: "R$ 90/pessoa", rating: 5, active: true },
  { id: "s2", name: "Foto Já", category: "fotografia", active: true, phone: "11 9999" }];
const PLAN = { summary: "Ativação.", timeline: [{ date: "2026-11-20", phase: "Pré", task: "Montagem" }], staff: [],
  budget: [{ category: "locacao", item: "Tenda", value: 800 }], budget_total: 800, risks: [], checklist: [] };
const EVENT = { id: "p1", kind: "evento", title: "Ativação na loja", status: "em_andamento", format: "Evento / Ativação", target_date: "2026-11-20",
  inputs: { idea: "Degustação", location: "Rua X, São Paulo" }, plan: PLAN, chat: [], created_at: "x", updated_at: "x", radar: {} };
const RADAR = { local: { name: "São Paulo", region: "São Paulo" }, atualizado_em: "2026-11-11T20:00:00Z",
  clima: { tipo: "previsao", data: "2026-11-20", condicao: "chuva", max: 31, min: 20, chance_chuva: 80, vento_kmh: 20 },
  alertas: [{ tipo: "chuva", gravidade: "alta", texto: "Chance de chuva de 80%: tenha plano B coberto." }],
  noticias: [{ tema: "clima", manchete: "Defesa Civil alerta para temporal", fonte: "G1", data: "2026-11-10", link: "https://g1.com/x" }], avisos: [] };

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  api.listSuppliers.mockResolvedValue({ suppliers: SUPPLIERS, categories: CATS });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim().startsWith(label)) as HTMLButtonElement;
const tick = () => act(async () => {});
const setValue = async (el: HTMLInputElement | HTMLSelectElement, value: string) => act(async () => {
  Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value")!.set!.call(el, value);
  el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
});
async function openEvent() {
  api.listProjects.mockResolvedValue({ projects: [EVENT], formats: [] });
  await act(async () => { root.render(<ProjectsPage kind="evento" />); }); await tick();
  await act(async () => { btn("Ativação na loja").click(); }); await tick();
}

describe("Evento: clima e notícias da região", () => {
  it("puxa a previsão, mostra alertas e notícias", async () => {
    api.refreshEventRadar.mockResolvedValue({ project: { ...EVENT, radar: RADAR } });
    await openEvent();
    expect(host.querySelector(".evRadar")?.textContent).toContain("Rua X, São Paulo");
    await act(async () => { btn("Puxar clima e notícias").click(); }); await tick();
    expect(api.refreshEventRadar).toHaveBeenCalledWith("p1");
    const radar = host.querySelector(".evRadar")!.textContent!;
    expect(radar).toContain("Previsão para 20/11: chuva");
    expect(radar).toContain("plano B coberto");
    expect(radar).toContain("Defesa Civil alerta para temporal");
    expect(host.querySelector(".evAlerts li.is-alta")).toBeTruthy();
  });

  it("sem local, o botão fica travado e pede o local", async () => {
    api.listProjects.mockResolvedValue({ projects: [{ ...EVENT, inputs: { idea: "x" } }], formats: [] });
    await act(async () => { root.render(<ProjectsPage kind="evento" />); }); await tick();
    await act(async () => { btn("Ativação na loja").click(); }); await tick();
    expect(btn("Puxar clima e notícias").disabled).toBe(true);
    expect(host.querySelector(".evRadar")?.textContent).toContain("Coloque o local do evento");
  });
});

describe("Evento: fornecedores", () => {
  it("aba Fornecedores cadastra e lista", async () => {
    api.listProjects.mockResolvedValue({ projects: [], formats: [] });
    api.createSupplier.mockResolvedValue({ supplier: { id: "s3", name: "Som Total", category: "outros", active: true } });
    await act(async () => { root.render(<ProjectsPage kind="evento" />); }); await tick();
    await act(async () => { btn("Fornecedores").click(); }); await tick();
    expect(host.querySelector(".supTable")?.textContent).toContain("Buffet Sabor");
    expect(host.querySelector(".supTable")?.textContent).toContain("R$ 90/pessoa");
    await act(async () => { btn("Novo fornecedor").click(); });
    await setValue(host.querySelector(".supForm input") as HTMLInputElement, "Som Total");
    await act(async () => { (host.querySelector(".supForm") as HTMLFormElement).requestSubmit(); }); await tick();
    expect(api.createSupplier.mock.calls[0][0].name).toBe("Som Total");
    expect(host.querySelector(".supTable")?.textContent).toContain("Som Total");
  });

  it("põe fornecedor no evento, muda status e lança no orçamento", async () => {
    api.listEventSuppliers.mockResolvedValue({ links: [] });
    api.linkEventSupplier.mockResolvedValue({ link: { id: "l1", project_id: "p1", supplier_id: "s1", item: "80 pessoas", status: "cotando", value: 7200, supplier: SUPPLIERS[0] } });
    api.updateEventSupplier.mockResolvedValue({ link: { id: "l1", project_id: "p1", supplier_id: "s1", item: "80 pessoas", status: "contratado", value: 7200 } });
    api.eventSuppliersToBudget.mockResolvedValue({ project: { ...EVENT, plan: { ...PLAN, budget: [...PLAN.budget, { category: "logistica", item: "Buffet Sabor (80 pessoas)", value: 7200, supplier_link_id: "l1" }], budget_total: 8000 } } });
    await openEvent();
    // a aba Fornecedores do detalhe do evento (a da página, no topo, é a primeira)
    const tabs = [...host.querySelectorAll("button")].filter((b) => b.textContent === "Fornecedores");
    await act(async () => { tabs[tabs.length - 1].click(); }); await tick();
    await setValue(host.querySelector('select[aria-label="Fornecedor para o evento"]') as HTMLSelectElement, "s1");
    await setValue(host.querySelector('input[aria-label="O que faz no evento"]') as HTMLInputElement, "80 pessoas");
    await setValue(host.querySelector('input[aria-label="Valor cotado"]') as HTMLInputElement, "7200");
    await act(async () => { btn("Pôr no evento").click(); }); await tick();
    expect(api.linkEventSupplier).toHaveBeenCalledWith("p1", { supplier_id: "s1", item: "80 pessoas", value: 7200 });
    await setValue(host.querySelector('.evSuppliers select[aria-label="Status"]') as HTMLSelectElement, "contratado"); await tick();
    expect(api.updateEventSupplier).toHaveBeenCalledWith("p1", "l1", { status: "contratado" });
    await act(async () => { btn("Lançar no orçamento").click(); }); await tick();
    expect(api.eventSuppliersToBudget).toHaveBeenCalledWith("p1");
  });
});
