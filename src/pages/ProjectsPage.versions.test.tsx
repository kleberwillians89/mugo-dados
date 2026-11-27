// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ listProjects: vi.fn(), createProject: vi.fn(), updateProject: vi.fn(), deleteProject: vi.fn(),
  generateProject: vi.fn(), researchProject: vi.fn(), chatProject: vi.fn(), projectToBrief: vi.fn(),
  listProjectVersions: vi.fn(), getProjectVersion: vi.fn(), restoreProjectVersion: vi.fn() }));
vi.mock("../app/projects", async (original) => ({ ...(await original<typeof import("../app/projects")>()), ...api }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "ruah", getActiveClientName: () => "Ruah" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ controls }: { controls?: React.ReactNode }) => <div>{controls}</div> }));
vi.mock("../components/goals/GoalsPanel", () => ({ default: ({ canManage, header }: { canManage: boolean; header: (b: React.ReactNode) => React.ReactNode }) =>
  <div data-testid="goals">{header(canManage ? <button type="button">+ Nova meta</button> : null)}metas da empresa</div> }));

import ProjectsPage from "./ProjectsPage";

const BASE = { id: "p1", kind: "evento", title: "Lançamento na loja", status: "fila", format: "Evento / Ativação", target_date: "2026-12-10",
  inputs: { idea: "Ativação com degustação" }, plan: {}, chat: [], created_at: "x", updated_at: "x" };

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  api.listProjectVersions.mockResolvedValue({ versions: [], available: true });
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim().startsWith(label)) as HTMLButtonElement;
const show = async (kind: "planejamento" | "evento") => { await act(async () => { root.render(<ProjectsPage kind={kind} />); }); await act(async () => {}); };
const type = async (el: HTMLInputElement | HTMLTextAreaElement, value: string) => act(async () => {
  Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value")!.set!.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
});

describe("Planejamento: salvamento automático e versões", () => {
  const plan = { big_idea: "Natal perfumado", strategy: "Presentes", kpis: [] };
  const proj = { ...BASE, kind: "planejamento", status: "em_andamento", format: null, inputs: { objective: "Vender kits" }, plan };

  it("salva sozinho o que foi editado e avisa quando salvou", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.listProjects.mockResolvedValue({ projects: [proj], formats: [] });
    api.updateProject.mockImplementation(async (_k: string, _id: string, patch: Record<string, unknown>) => ({ project: { ...proj, ...patch, updated_at: "y" } }));
    await show("planejamento");
    await act(async () => { (host.querySelector(".projCard") as HTMLButtonElement).click(); });
    const field = [...host.querySelectorAll<HTMLLabelElement>(".projEditFields label")].find((l) => l.textContent?.startsWith("Estratégia"))!.querySelector("textarea")!;
    await type(field, "Presentes com entrega em 24 h");
    expect(host.textContent).toContain("Alterações pendentes");
    await act(async () => { vi.advanceTimersByTime(1300); });
    await act(async () => {});
    expect(api.updateProject).toHaveBeenCalledWith("planejamento", "p1", expect.objectContaining({
      plan: expect.objectContaining({ strategy: "Presentes com entrega em 24 h", big_idea: "Natal perfumado" }),
      inputs: expect.objectContaining({ objective: "Vender kits" }) }));
    expect(host.querySelector(".projSaveState")?.textContent).toMatch(/Salvo às/);
    vi.useRealTimers();
  });

  it("plano aprovado: refazer pede confirmação (a versão atual fica guardada)", async () => {
    api.listProjects.mockResolvedValue({ projects: [{ ...proj, status: "finalizado" }], formats: [] });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await show("planejamento");
    await act(async () => { (host.querySelector(".projCard") as HTMLButtonElement).click(); });
    await act(async () => { btn("Refazer com IA").click(); });
    expect(confirm).toHaveBeenCalled();
    expect(api.generateProject).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("lista versões com número, data e autor, abre uma e restaura como versão nova", async () => {
    api.listProjects.mockResolvedValue({ projects: [proj], formats: [] });
    api.listProjectVersions.mockResolvedValue({ available: true, versions: [
      { version: 2, origin: "ia", origin_label: "Gerada pela IA", title: "x", status: "em_andamento", note: "mais BF", author: "Kleber", created_at: "2026-11-24T20:00:00Z" },
      { version: 1, origin: "ia", origin_label: "Gerada pela IA", title: "x", status: "fila", note: null, author: "Julia", created_at: "2026-11-20T10:00:00Z" }] });
    api.getProjectVersion.mockResolvedValue({ version: { version: 1, origin: "ia", origin_label: "Gerada pela IA", title: "x", status: "fila", note: null,
      author: "Julia", created_at: "2026-11-20T10:00:00Z", inputs: {}, plan: { big_idea: "Ideia antiga" } } });
    api.restoreProjectVersion.mockResolvedValue({ project: { ...proj, plan: { big_idea: "Ideia antiga" }, updated_at: "z" } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await show("planejamento");
    await act(async () => { (host.querySelector(".projCard") as HTMLButtonElement).click(); });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); });  // a lista carrega logo depois de abrir
    await act(async () => { btn("Versão 2").click(); });
    const list = host.querySelector(".projVersionList")!.textContent!;
    expect(list).toContain("Versão 2 · atual");
    expect(list).toContain("Kleber");
    expect(list).toContain("Julia");
    await act(async () => { [...host.querySelectorAll<HTMLButtonElement>(".projVersionList button")][1].click(); });
    expect(host.querySelector(".projVersionPlan")?.textContent).toContain("Ideia antiga");
    await act(async () => { btn("Restaurar esta versão").click(); });
    expect(api.restoreProjectVersion).toHaveBeenCalledWith("planejamento", "p1", 1);
    vi.restoreAllMocks();
  });

  it("o formulário novo guarda o rascunho e limpa depois de criar", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.listProjects.mockResolvedValue({ projects: [], formats: [] });
    window.sessionStorage.setItem("mugo:projects:new", "planejamento");
    await show("planejamento");
    await type(host.querySelector(".projNew input") as HTMLInputElement, "Dia dos Pais");
    await act(async () => { vi.advanceTimersByTime(700); });
    expect(JSON.parse(window.localStorage.getItem("mugo:project-draft:ruah:planejamento") || "{}").title).toBe("Dia dos Pais");
    act(() => root.unmount()); root = createRoot(host);
    window.sessionStorage.setItem("mugo:projects:new", "planejamento");
    await show("planejamento");
    expect((host.querySelector(".projNew input") as HTMLInputElement).value).toBe("Dia dos Pais");  // voltou com o rascunho
    api.createProject.mockResolvedValue({ project: { ...proj, id: "p9", title: "Dia dos Pais", plan: {} } });
    await act(async () => { btn("Só criar o card").click(); });
    expect(window.localStorage.getItem("mugo:project-draft:ruah:planejamento")).toBeNull();
    vi.useRealTimers();
    window.localStorage.clear(); window.sessionStorage.clear();
  });
});
