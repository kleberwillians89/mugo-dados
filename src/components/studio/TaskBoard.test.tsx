// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const crm = vi.hoisted(() => ({ listCrmTasks: vi.fn(), taskApproval: vi.fn(), taskHistory: vi.fn(), updateTask: vi.fn(), createTask: vi.fn(), deleteTask: vi.fn() }));
vi.mock("../../app/crm", async (original) => ({ ...(await original<typeof import("../../app/crm")>()), ...crm }));
const studio = vi.hoisted(() => ({ getPipeline: vi.fn(), updateCalendarItem: vi.fn(), decideCalendarItem: vi.fn(async () => ({ item: {} })),
  listItemReferences: vi.fn(async () => ({ references: [] })), listContacts: vi.fn(), sendForApproval: vi.fn(), listItemComments: vi.fn(async () => ({ comments: [] })) }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));
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
  studio.getPipeline.mockResolvedValue({ items: [] });
  studio.updateCalendarItem.mockResolvedValue({ item: {} });
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

  it("ajuste do Calendário: a equipe manda o ajuste feito ao cliente pela própria tarefa", async () => {
    const itemId = "11111111-1111-1111-1111-111111111111";
    crm.listCrmTasks.mockImplementation(async (status?: string) => ({ available: true,
      tasks: status === "completed" ? [] : [task("changes", { id: "t-cal", title: "Ajuste: Black Friday (27/11)", calendar_item_id: itemId, due_date: "2026-11-27" })] }));
    studio.getPipeline.mockResolvedValue({ items: [{ id: itemId, title: "Black Friday", status: "rejeitado", stage: "ajuste", scheduled_at: "2026-11-27T22:00:00Z", format: "reels" }] });
    studio.updateCalendarItem.mockResolvedValue({ item: {} });
    studio.listContacts.mockResolvedValue({ whatsapp_channel: "mugozap", contacts: [{ id: "c1", name: "Gabi", phone: "1", role: null, receives: ["conteudo"], is_primary: true }] });
    studio.sendForApproval.mockResolvedValue({ request_id: "r1", link: "https://x/aprovar/t", whatsapp_url: "https://wa.me/x", whatsapp_text: "oi", whatsapp: { status: "enviado", channel: "mugozap", text: "oi" } });
    await show(<TaskBoard canManage isAgency />);
    expect(host.textContent).toContain("Ajuste: Black Friday (27/11)");
    expect(host.querySelector(".taskFromCalendar")?.textContent).toBe("Calendário");
    expect([...host.querySelectorAll(".taskQuick button")].map((b) => b.textContent)).toEqual(["Enviar ao cliente →", "Calendário →"]);
    await act(async () => { (host.querySelector(".kanbanTitle") as HTMLButtonElement).click(); });
    expect(host.querySelector("[data-drawer]")?.textContent).toContain("Ligada a um post do Calendário");
    expect([...host.querySelectorAll("[data-drawer] button")].map((b) => b.textContent)).not.toContain("Enviar para aprovação interna");
    await click("Ajuste feito: enviar ao cliente");
    expect(studio.updateCalendarItem).toHaveBeenCalledWith(itemId, { status: "em_revisao" });
    expect(studio.sendForApproval).toHaveBeenCalledWith({ month: "2026-11", item_ids: [itemId], contact_id: "c1", send_whatsapp: true, notify_team: true });
    expect(host.textContent).toContain("Gabi recebeu o link no WhatsApp");
  });

  it("tarefa do Calendário com o cliente: equipe marca aprovado ou pede novo ajuste", async () => {
    const itemId = "22222222-2222-2222-2222-222222222222";
    crm.listCrmTasks.mockImplementation(async (status?: string) => ({ available: true,
      tasks: status === "completed" ? [] : [task("client_review", { id: "t-cli", title: "Ajuste: Reels", calendar_item_id: itemId })] }));
    studio.getPipeline.mockResolvedValue({ items: [] });
    studio.updateCalendarItem.mockResolvedValue({ item: {} });
    await show(<TaskBoard canManage isAgency />);
    await act(async () => { (host.querySelector(".kanbanTitle") as HTMLButtonElement).click(); });
    await click("Cliente aprovou ✓");
    expect(studio.updateCalendarItem).toHaveBeenCalledWith(itemId, { status: "aprovado" });
    expect(host.textContent).toContain("Post aprovado.");
  });

  it("posts do Fluxo de aprovação entram no quadro; cliente aprova ou pede ajuste pela tela do celular", async () => {
    const post = { id: "p1", title: "Reels Black Friday", format: "reels", scheduled_at: "2026-11-27T22:00:00Z", status: "em_revisao", stage: "com_cliente",
      caption_draft: "Oferta da semana", art_url: null, hook: null, request: { contact_name: "Gabi" }, client_feedback: null };
    studio.getPipeline.mockImplementation(async (month: string) => ({ items: month.endsWith(String(new Date().getMonth() + 1).padStart(2, "0")) ? [post] : [] }));
    crm.listCrmTasks.mockResolvedValue({ available: true, tasks: [] });
    await show(<TaskBoard />);
    const column = [...host.querySelectorAll(".kanbanCol")].find((c) => c.querySelector("header b")?.textContent === "Aprovação do cliente")!;
    expect(column.textContent).toContain("Reels Black Friday");
    expect(column.textContent).toContain("com Gabi");
    await click("Aprovar / ajuste");
    expect(host.querySelector(".phoneFrame")).toBeTruthy();
    expect(host.textContent).toContain("Oferta da semana");
    await click("Pedir ajuste");
    expect(host.textContent).toContain("Escreva o que precisa mudar");
    expect(studio.decideCalendarItem).not.toHaveBeenCalled();
    await click("Aprovar");
    expect(studio.decideCalendarItem).toHaveBeenCalledWith("p1", "aprovado", undefined);
    expect(host.textContent).toContain("Post aprovado.");
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
