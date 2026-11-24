// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const crm = vi.hoisted(() => ({ listCrmTasks: vi.fn(), listClientTasks: vi.fn() }));
vi.mock("../../app/crm", async (original) => ({ ...(await original<typeof import("../../app/crm")>()), ...crm }));
const board = vi.hoisted(() => vi.fn((props: { canManage: boolean; isAgency: boolean }) => <div data-testid="board">quadro {String(props.canManage)} {String(props.isAgency)}</div>));
vi.mock("../studio/TaskBoard", () => ({ default: board }));
vi.mock("../studio/ClientTasks", () => ({ default: () => <div data-testid="client">tarefas do cliente</div> }));

import WorkKanban from "./WorkKanban";
import { kanbanCache } from "./workKanban.helpers";
import { WorkContext, type WorkValue } from "../../app/WorkContext";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); kanbanCache.clear(); window.localStorage.clear(); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

const TEAM: WorkValue = { route: "media", clientId: "ruah", userId: "u1", mode: "team", canManage: true, isAgency: false };
const yesterday = (() => { const d = new Date(); d.setDate(d.getDate() - 1); return d.toISOString().slice(0, 10); })();
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim().startsWith(label));
async function show(value: WorkValue | null) {
  await act(async () => { root.render(value ? <WorkContext.Provider value={value}><WorkKanban /></WorkContext.Provider> : <WorkKanban />); });
  await act(async () => {});
}

describe("Kanban integrado e recolhível", () => {
  it("recolhido: faixa com pendências da equipe, sem montar o quadro", async () => {
    crm.listCrmTasks.mockResolvedValue({ available: true, tasks: [
      { status: "in_progress", due_date: null }, { status: "pending", due_date: yesterday }, { status: "internal_review", due_date: null },
      { status: "completed", due_date: yesterday },
    ] });
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
    await show(TEAM);
    await show({ ...TEAM, route: "calendar" });
    expect(crm.listCrmTasks).toHaveBeenCalledTimes(1);
  });
});
