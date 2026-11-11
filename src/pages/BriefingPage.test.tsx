// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ listBriefs: vi.fn(), createBrief: vi.fn(), sendBrief: vi.fn(), briefTask: vi.fn(), approveBrief: vi.fn(),
  updateBrief: vi.fn(), regenerateBrief: vi.fn() }));
vi.mock("../app/briefs", () => api);
vi.mock("../app/crm", async (original) => ({ ...(await original<typeof import("../app/crm")>()),
  listAssignees: vi.fn(async () => ({ available: true, people: [{ user_id: "u-liliu", name: "Liliu" }] })) }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "ruah", getActiveClientName: () => "Ruah" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/data/PageHeader", () => ({ default: () => null }));

import BriefingPage from "./BriefingPage";

const BRIEF = { id: "b1", status: "pronto", request: "BF de decant com 3 mil", created_at: "2026-11-11T20:00:00Z", created_side: "mugo", created_by_name: "Kleber",
  brief: { title: "Black Friday decant", summary: "Campanha de decant na BF.", objective: "Vender decants", deadline: "2026-11-27", goal: "120 pedidos",
    client_summary: "Vamos lançar a campanha até 27/11.", deliverables: ["4 Reels"], destinations: [{ key: "social_media", why: "Conteúdo do mês" }],
    roles: [{ role: "designer", what: "Capas dos Reels" }] }, destinations: {}, tasks: [], progress: { done: 0, total: 0 } };

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement;
const show = async () => { await act(async () => { root.render(<BriefingPage />); }); await act(async () => {}); };

describe("Briefing", () => {
  it("equipe monta, leva para a Social Media e cria a tarefa da designer", async () => {
    api.listBriefs.mockResolvedValue({ briefs: [], team: true, destinations: {}, roles: {} });
    api.createBrief.mockResolvedValue({ brief: BRIEF });
    api.sendBrief.mockResolvedValue({ brief: { ...BRIEF, status: "distribuido", destinations: { social_media: { status: "feito", detail: "Esteira de agentes rodando com este foco", at: "x" } } } });
    api.briefTask.mockResolvedValue({ brief: { ...BRIEF, status: "distribuido", tasks: [{ task_id: "t1", role: "designer", name: "Liliu", at: "x" }] } });
    await show();
    const area = host.querySelector("#brief-request") as HTMLTextAreaElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(area, "BF de decant com 3 mil");
      area.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { btn("Montar briefing").click(); });
    expect(api.createBrief).toHaveBeenCalledWith("BF de decant com 3 mil", []);
    expect(host.textContent).toContain("Vender decants");
    expect(host.querySelector(".briefDestinations li.is-suggested")?.textContent).toContain("Conteúdo do mês");
    const send = host.querySelector(".briefDestinations li.is-suggested button") as HTMLButtonElement;
    await act(async () => { send.click(); });
    expect(api.sendBrief).toHaveBeenCalledWith("b1", "social_media");
    expect(host.textContent).toContain("Esteira de agentes rodando");
    const select = host.querySelector(".briefPerson select") as HTMLSelectElement;
    await act(async () => { select.value = "u-liliu"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    await act(async () => { (host.querySelector(".briefPerson button") as HTMLButtonElement).click(); });
    expect(api.briefTask).toHaveBeenCalledWith("b1", { role: "designer", assignee_user_id: "u-liliu", assignee_name: "Liliu", due_date: null, note: null });
    expect(host.textContent).toContain("Tarefa de Liliu");
  });

  it("cliente vê só a versão curta e o andamento", async () => {
    api.listBriefs.mockResolvedValue({ team: false, destinations: {}, roles: {}, briefs: [{ id: "b1", status: "distribuido", request: "Quero BF",
      created_at: "2026-11-11T20:00:00Z", created_side: "cliente", brief: { title: "Black Friday decant", client_summary: "Vamos lançar a campanha até 27/11.",
        deadline: "2026-11-27", goal: "120 pedidos" }, progress: { done: 1, total: 3 } }] });
    await show();
    expect(host.textContent).toContain("Vamos lançar a campanha até 27/11.");
    expect(host.textContent).toContain("1 de 3 entregas concluídas");
    expect(host.querySelector(".briefDestinations")).toBeNull();
    expect(btn("Enviar pedido")).toBeTruthy();
  });
});
