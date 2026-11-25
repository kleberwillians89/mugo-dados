// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const crm = vi.hoisted(() => ({ listCrmTasks: vi.fn(), listClientTasks: vi.fn(), listTaskNotifications: vi.fn(), markTaskNotificationRead: vi.fn() }));
vi.mock("../../app/crm", async (original) => ({ ...(await original<typeof import("../../app/crm")>()), ...crm }));
const board = vi.hoisted(() => vi.fn((props: { canManage: boolean; isAgency: boolean }) => <div data-testid="board">quadro {String(props.canManage)} {String(props.isAgency)}</div>));
vi.mock("../studio/TaskBoard", () => ({ default: board }));
vi.mock("../studio/ClientTasks", () => ({ default: () => <div data-testid="client">tarefas do cliente</div> }));

import WorkKanban from "./WorkKanban";
import { OPEN_TASK_EVENT, kanbanCache } from "./workKanban.helpers";
import { WorkContext, type WorkValue } from "../../app/WorkContext";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); kanbanCache.clear(); window.localStorage.clear();
  crm.listTaskNotifications.mockResolvedValue({ messages: [], unread: 0 });
  crm.markTaskNotificationRead.mockResolvedValue({ ok: true });
});
const collapsed = (...users: string[]) => users.forEach((u) => window.localStorage.setItem(`mugo:kanban:open:${u}`, "0"));
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

const TEAM: WorkValue = { route: "media", clientId: "ruah", userId: "u1", mode: "team", canManage: true, isAgency: false };
// Data local (não UTC): depois das 21h em São Paulo, o "ontem" em UTC já seria hoje e a tarefa não estaria atrasada.
const yesterday = (() => { const d = new Date(); d.setDate(d.getDate() - 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; })();
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim().startsWith(label));
async function show(value: WorkValue | null, place: "shell" | "home" = "shell") {
  await act(async () => { root.render(value ? <WorkContext.Provider value={value}><WorkKanban place={place} /></WorkContext.Provider> : <WorkKanban place={place} />); });
  await act(async () => {});
}

describe("Kanban integrado e recolhível", () => {
  it("recolhido: faixa com pendências da equipe, sem montar o quadro", async () => {
    crm.listCrmTasks.mockResolvedValue({ available: true, tasks: [
      { status: "in_progress", due_date: null }, { status: "pending", due_date: yesterday }, { status: "internal_review", due_date: null },
      { status: "completed", due_date: yesterday },
    ] });
    collapsed("u1");
    await show(TEAM);
    expect(host.textContent).toContain("Kanban");
    expect(host.textContent).toMatch(/2\s*em andamento/);
    expect(host.textContent).toMatch(/1\s*em aprovação/);
    expect(host.textContent).toMatch(/1\s*atrasada/);  // concluída atrasada não conta
    expect(host.querySelector("[data-testid=board]")).toBeNull();
    expect(crm.listClientTasks).not.toHaveBeenCalled();
  });

  it("expandir mostra o quadro de Tarefas com as permissões do contexto e a escolha fica salva por pessoa", async () => {
    crm.listCrmTasks.mockResolvedValue({ available: true, tasks: [] });
    collapsed("u1", "u2");
    await show(TEAM);
    await act(async () => { btn("Expandir")!.click(); });
    expect(host.querySelector("[data-testid=board]")?.textContent).toBe("quadro true false");
    expect(window.localStorage.getItem("mugo:kanban:open:u1")).toBe("1");
    await act(async () => root.unmount()); root = createRoot(host);
    await show(TEAM);
    expect(host.querySelector("[data-testid=board]")).not.toBeNull();  // outra tela, mesma pessoa: continua expandido
    await show({ ...TEAM, userId: "u2" });
    expect(host.querySelector("[data-testid=board]")).toBeNull();      // outra pessoa: escolha dela
  });

  it("cliente vê só as tarefas visíveis a ele (outro endpoint e outro quadro)", async () => {
    crm.listClientTasks.mockResolvedValue({ available: true, tasks: [{ status: "client_review", due_date: null }] });
    collapsed("u1");
    await show({ ...TEAM, mode: "client", canManage: false });
    expect(crm.listCrmTasks).not.toHaveBeenCalled();
    expect(host.textContent).toMatch(/1\s*em aprovação/);
    await act(async () => { btn("Expandir")!.click(); });
    expect(host.querySelector("[data-testid=client]")).not.toBeNull();
    expect(host.querySelector("[data-testid=board]")).toBeNull();
  });

  it("não aparece fora dos processos, sem permissão de tarefas ou sem contexto", async () => {
    crm.listCrmTasks.mockResolvedValue({ available: true, tasks: [] });
    for (const value of [{ ...TEAM, route: "tasks" as const }, { ...TEAM, route: "home" as const }, { ...TEAM, route: "internal_approval" as const },
      { ...TEAM, mode: null }, null]) {
      await show(value);
      expect(host.querySelector(".workKanban")).toBeNull();
    }
    expect(crm.listCrmTasks).not.toHaveBeenCalled();
  });

  it("não busca de novo a cada troca de tela (cache curto)", async () => {
    crm.listCrmTasks.mockResolvedValue({ available: true, tasks: [] });
    collapsed("u1");
    await show(TEAM);
    await show({ ...TEAM, route: "calendar" });
    expect(crm.listCrmTasks).toHaveBeenCalledTimes(1);
  });

  it("primeira vez: abre expandido; sem link para a página completa", async () => {
    crm.listCrmTasks.mockResolvedValue({ available: true, tasks: [] });
    await show(TEAM);
    expect(host.querySelector("[data-testid=board]")).not.toBeNull();
    expect(host.textContent).not.toContain("Ver página completa");
  });

  it("no Início aparece pela própria página", async () => {
    crm.listCrmTasks.mockResolvedValue({ available: true, tasks: [] });
    await show({ ...TEAM, route: "home" }, "home");
    expect(host.querySelector(".workKanban.is-home")).not.toBeNull();
  });

  it("avisos de atribuição ficam no sino: abrir marca como lido e pede a tarefa ao quadro", async () => {
    crm.listCrmTasks.mockResolvedValue({ available: true, tasks: [] });
    crm.listTaskNotifications.mockResolvedValue({ unread: 1, messages: [
      { id: "n1", task_id: "t9", title: "Nova tarefa para você", body: "Post BF", task_url: "", read_at: null, whatsapp_status: "sent", created_at: "" }] });
    const opened = vi.fn();
    window.addEventListener(OPEN_TASK_EVENT, opened);
    collapsed("u1");
    await show(TEAM);
    const bell = host.querySelector<HTMLButtonElement>(".workKanbanBell")!;
    expect(bell.getAttribute("aria-label")).toContain("1 não lido");
    await act(async () => { bell.click(); });
    await act(async () => { [...host.querySelectorAll(".workKanbanNoticeList button")][0].dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(crm.markTaskNotificationRead).toHaveBeenCalledWith("n1");
    expect((opened.mock.calls[0][0] as CustomEvent).detail).toEqual({ taskId: "t9" });
    expect(host.querySelector("[data-testid=board]")).not.toBeNull();  // abre o quadro para mostrar a tarefa
    expect(new URL(window.location.href).searchParams.get("task")).toBe("t9");
    window.removeEventListener(OPEN_TASK_EVENT, opened);
    window.history.replaceState(null, "", "/");
  });

  it("cliente não vê o sino de avisos da equipe", async () => {
    crm.listClientTasks.mockResolvedValue({ available: true, tasks: [] });
    await show({ ...TEAM, mode: "client", canManage: false });
    expect(host.querySelector(".workKanbanBell")).toBeNull();
    expect(crm.listTaskNotifications).not.toHaveBeenCalled();
  });
});
