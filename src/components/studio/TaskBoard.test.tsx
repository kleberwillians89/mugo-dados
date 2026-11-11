// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const crm = vi.hoisted(() => ({ listCrmTasks: vi.fn(), taskApproval: vi.fn(), taskHistory: vi.fn(), updateTask: vi.fn(), createTask: vi.fn(), deleteTask: vi.fn() }));
vi.mock("../../app/crm", async (original) => ({ ...(await original<typeof import("../../app/crm")>()), ...crm }));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "ruah", getActiveClientName: () => "Ruah" }));
vi.mock("../Drawer", () => ({ default: ({ open, children }: { open: boolean; children: React.ReactNode }) => (open ? <div data-drawer>{children}</div> : null) }));

import TaskBoard from "./TaskBoard";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const task = (status: string, extra = {}) => ({ id: `t-${status}`, title: `Post ${status}`, status, priority: null, due_date: null, due_time: null, starts_at: null,
  category: null, task_type: null, tags: [], notes: null, updated_at: null, assignee: null, visible_to_client: true, needs_client_approval: true,
  deliverable_url: "https://drive.google.com/x", approval_round: 1, ...extra });
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  crm.listCrmTasks.mockImplementation(async (status?: string) => ({ available: true,
    tasks: status === "completed" ? [] : [task("in_progress"), task("internal_review"), task("client_review")] }));
  crm.taskHistory.mockResolvedValue({ events: [{ id: "e1", kind: "enviado_interno", internal: true, comment: null, actor_name: "julia", actor_side: "mugo", created_at: "2026-11-10T20:00:00Z" }] });
  crm.taskApproval.mockImplementation(async (id: string, action: string) => ({ task: task(action === "client_approve" ? "completed" : action === "client_changes" ? "changes" : "internal_review", { id }), events: [] }));
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };
const click = async (label: string) => {
  const button = [...host.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement;
  expect(button, label).toBeTruthy();
  await act(async () => { button.click(); });
};

describe("Tarefas com aprovação", () => {
  it("equipe vê aprovação interna e envia/aprova pelo card", async () => {
    await show(<TaskBoard canManage isAgency />);
    const columns = [...host.querySelectorAll(".kanbanCol header b")].map((b) => b.textContent);
    expect(columns).toEqual(["Pendente", "Em produção", "Ajustes", "Aprovação interna", "Aprovação do cliente", "Aprovada / concluída"]);
    await click("Enviar p/ aprovação →");
    expect(crm.taskApproval).toHaveBeenCalledWith("t-in_progress", "submit", undefined, false);
    await click("Aprovar ✓");
    expect(crm.taskApproval).toHaveBeenLastCalledWith(expect.stringMatching(/^t-/), "internal_approve", undefined, false);
  });

  it("ajuste do Calendário: tarefa acompanha o post e a aprovação fica no Calendário", async () => {
    crm.listCrmTasks.mockImplementation(async (status?: string) => ({ available: true,
      tasks: status === "completed" ? [] : [task("changes", { id: "t-cal", title: "Ajuste: Black Friday (27/11)", calendar_item_id: "11111111-1111-1111-1111-111111111111" })] }));
    await show(<TaskBoard canManage isAgency />);
    expect(host.textContent).toContain("Ajuste: Black Friday (27/11)");
    expect(host.querySelector(".taskFromCalendar")?.textContent).toBe("Calendário");
    expect([...host.querySelectorAll(".taskQuick button")].map((b) => b.textContent)).toEqual(["Abrir no Calendário →"]);
    await act(async () => { (host.querySelector(".kanbanTitle") as HTMLButtonElement).click(); });
    expect(host.querySelector("[data-drawer]")?.textContent).toContain("nasceu de um ajuste no Calendário");
    expect([...host.querySelectorAll("[data-drawer] button")].map((b) => b.textContent)).not.toContain("Enviar para aprovação interna");
  });

  it("cliente não vê a etapa interna; pede ajuste com comentário pela tarefa aberta", async () => {
    await show(<TaskBoard />);
    expect([...host.querySelectorAll(".kanbanCol header b")].map((b) => b.textContent)).not.toContain("Aprovação interna");
    await click("Pedir ajuste");
    expect(host.querySelector("[data-drawer]")?.textContent).toContain("julia enviou para aprovação interna");
    const textarea = [...host.querySelectorAll("[data-drawer] textarea")].pop() as HTMLTextAreaElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, "Trocar a foto da capa");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const ajuste = [...host.querySelectorAll("[data-drawer] button")].find((b) => b.textContent === "Pedir ajuste") as HTMLButtonElement;
    await act(async () => { ajuste.click(); });
    expect(crm.taskApproval).toHaveBeenCalledWith("t-client_review", "client_changes", "Trocar a foto da capa", false);
    expect(host.textContent).toContain("Ajuste pedido.");
  });
});
