// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const crm = vi.hoisted(() => ({ listCrmTasks: vi.fn(), taskApproval: vi.fn(), taskHistory: vi.fn(), updateTask: vi.fn(), createTask: vi.fn(), transitionTask: vi.fn(), cancelTask: vi.fn(),
  listAssignees: vi.fn(async () => ({ available: true, people: [{ user_id: "u-liliu", name: "Liliu" }, { user_id: "u-maria", name: "Maria Eduarda" }] })) }));
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
  crm.transitionTask.mockImplementation(async (id: string, status: string) => ({ task: task(status, { id }) }));
  crm.cancelTask.mockImplementation(async (id: string) => ({ ok: true, task: task("cancelled", { id }) }));
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };
const click = async (label: string) => {
  const button = [...host.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement;
  expect(button, label).toBeTruthy();
  await act(async () => { button.click(); });
};

const open = async (title: string) => {
  const button = [...host.querySelectorAll(".kanbanTitle")].find((b) => b.textContent === title) as HTMLButtonElement;
  expect(button, title).toBeTruthy();
  await act(async () => { button.click(); });
};
const drawerButtons = () => [...host.querySelectorAll("[data-drawer] button")].map((b) => b.textContent);

describe("Tarefas com aprovação", () => {
  it("equipe vê aprovação interna; o card só informa e as ações ficam dentro da tarefa", async () => {
    await show(<TaskBoard canManage isAgency />);
    const columns = [...host.querySelectorAll(".kanbanCol header b")].map((b) => b.textContent);
    expect(columns).toEqual(["Pendente", "Em produção", "Ajustes", "Aprovação interna", "Aprovação do cliente", "Aprovada / concluída"]);
    expect(host.querySelector(".taskQuick")).toBeNull();
    expect(host.querySelector(".kanbanCol .taskCard button:not(.kanbanTitle)")).toBeNull();
    await open("Post in_progress");
    await click("Enviar para aprovação interna");
    expect(crm.taskApproval).toHaveBeenCalledWith("t-in_progress", "submit", undefined, false);
    await open("Post internal_review");
    await click("Aprovar e enviar ao cliente");
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
    expect(host.querySelector(".taskQuick")).toBeNull();
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
    // Tarefas abre como quadro independente; posts do calendário são opt-in.
    expect(host.textContent).not.toContain("Reels Black Friday");
    await click("Tudo + Calendário");
    const column = [...host.querySelectorAll(".kanbanCol")].find((c) => c.querySelector("header b")?.textContent === "Aprovação do cliente")!;
    expect(column.textContent).toContain("Reels Black Friday");
    expect(column.textContent).toContain("Esperando aprovação do cliente");
    await open("Reels Black Friday");
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
    await open("Post client_review");
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

  it("designer vê só as tarefas dela, envia para aprovação mas não aprova", async () => {
    crm.listCrmTasks.mockImplementation(async (status?: string) => ({ available: true, scope: { mine_only: true, can_approve: false },
      tasks: status === "completed" ? [] : [task("in_progress", { visible_to_client: false, assignee: { name: "Liliu", color: null, user_id: "u-liliu" } }),
        task("internal_review", { visible_to_client: false })] }));
    await show(<TaskBoard canManage />);
    expect(host.textContent).toContain("Você vê as tarefas em que é responsável");
    await open("Post internal_review");
    expect(drawerButtons()).not.toContain("Aprovar");
    await open("Post in_progress");
    await click("Enviar para aprovação interna");
    expect(crm.taskApproval).toHaveBeenCalledWith("t-in_progress", "submit", undefined, false);
  });

  it("quem tem aprovação interna (ex.: Maria Eduarda) aprova; responsável é escolhido entre os integrantes", async () => {
    crm.listCrmTasks.mockImplementation(async (status?: string) => ({ available: true, scope: { mine_only: false, can_approve: true },
      tasks: status === "completed" ? [] : [task("internal_review", { visible_to_client: false })] }));
    crm.updateTask.mockImplementation(async (id: string, input: object) => ({ task: task("internal_review", { id, ...input }) }));
    await show(<TaskBoard canManage />);
    await open("Post internal_review");
    expect(drawerButtons()).toContain("Aprovar");
    await click("Escolher entre todos");  // sem área escolhida, a lista de pessoas só aparece quando pedida
    const choice = [...host.querySelectorAll("[data-drawer] .taskAssigneeOptions label")]
      .find((label) => label.textContent?.includes("Liliu"))?.querySelector("input") as HTMLInputElement;
    expect(choice).toBeTruthy();
    await act(async () => { choice.click(); });
    const form = host.querySelector("[data-drawer] form") as HTMLFormElement;
    await act(async () => { form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    const sent = crm.updateTask.mock.calls[0][1] as { assignee_user_id: string; assignee_name: string; assignee_user_ids?: string[] };
    expect([sent.assignee_user_id, sent.assignee_name]).toEqual(["u-liliu", "Liliu"]);
    expect(sent.assignee_user_ids).toBeUndefined(); // legacy-safe for a single responsible person
  });
});

describe("cartão limpo e Nova tarefa simples (spec do Danilo)", () => {
  it("card em Ajustes mostra o que mudar, o nome (não o e-mail) e nenhum botão de ação", async () => {
    crm.listCrmTasks.mockImplementation(async (status?: string) => ({ available: true, tasks: status === "completed" ? [] : [
      task("changes", { title: "Ajuste: capa", change_note: "Trocar a foto da capa por uma de produto", category: "Design",
        assignees: [{ name: "mduda.mugo@gmail.com", color: "#3a7", user_id: "u1" }] })] }));
    await show(<TaskBoard canManage isAgency />);
    const card = host.querySelector(".kanbanCol.is-task-changes .taskCard")!;
    expect(card.textContent).toContain("Ajustar: Trocar a foto da capa por uma de produto");
    expect(card.textContent).toContain("mduda.mugo");
    expect(card.textContent).not.toContain("@gmail.com");
    expect(card.textContent).toContain("Design");
    expect(card.querySelectorAll("button")).toHaveLength(1);  // só o título, que abre a tarefa
  });

  it("Nova tarefa: Título → Tarefa → Link → Departamento → Responsáveis → opcionais; nasce Pendente, interna e sem WhatsApp", async () => {
    crm.listAssignees.mockResolvedValue({ available: true, people: [
      { user_id: "u-liliu", name: "Liliu", departments: ["Design"] }, { user_id: "u-julia", name: "Julia", departments: ["Social Media"] }] });
    crm.createTask.mockResolvedValue({ task: task("pending") });
    await show(<TaskBoard canManage isAgency />);
    const columnsWithAdd = [...host.querySelectorAll(".kanbanCol")].filter((c) => c.querySelector(".taskAddCard")).map((c) => c.querySelector("header b")?.textContent);
    expect(columnsWithAdd).toEqual(["Pendente"]);  // ninguém cria tarefa direto em outra etapa
    await click("+ Nova tarefa");
    const drawer = host.querySelector("[data-drawer]")!;
    const labels = [...drawer.querySelectorAll("fieldset label.ds-field, fieldset legend")].map((l) => (l.childNodes[0]?.textContent || "").trim());
    expect(labels.slice(0, 6)).toEqual(["Título", "Tarefa", "Link da entrega (Drive, Canva, Figma…)", "Departamento", "Responsáveis", "Prioridade"]);
    for (const gone of ["Etapa", "Visível ao cliente", "Exigir aprovação do cliente", "Avisar responsáveis também pelo WhatsApp"]) expect(drawer.textContent).not.toContain(gone);
    expect(drawer.textContent).toContain("Escolha o departamento para ver quem é da área.");
    expect(drawer.textContent).not.toContain("Liliu");
    const set = async (el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) => act(async () => {
      const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
      el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
    });
    await set(drawer.querySelector("input[required]") as HTMLInputElement, "Peças de dezembro");
    await set(drawer.querySelector("textarea") as HTMLTextAreaElement, "3 posts e 2 stories");
    await set([...drawer.querySelectorAll("select")].find((s) => s.textContent?.includes("Selecione a área")) as HTMLSelectElement, "Design");
    expect(drawer.textContent).toContain("Liliu");
    expect(drawer.textContent).not.toContain("Julia");  // só quem é da área, até pedir as outras
    await act(async () => { ([...drawer.querySelectorAll(".taskAssigneeOptions label")].find((l) => l.textContent?.includes("Liliu"))!.querySelector("input") as HTMLInputElement).click(); });
    await act(async () => { (drawer.querySelector("form") as HTMLFormElement).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    const sent = crm.createTask.mock.calls[0][0];
    expect(sent).toMatchObject({ title: "Peças de dezembro", notes: "3 posts e 2 stories", category: "Design", status: "pending", priority: null,
      due_date: null, send_whatsapp: false, visible_to_client: false, needs_client_approval: false, assignee_user_id: "u-liliu" });
  });

  it("editar não mexe em etapa, visibilidade nem aprovação; Iniciar e Concluir ficam dentro da tarefa", async () => {
    crm.listCrmTasks.mockImplementation(async (status?: string) => ({ available: true, tasks: status === "completed" ? [] : [
      task("pending", { visible_to_client: true, needs_client_approval: true }), task("in_progress", { visible_to_client: false })] }));
    crm.updateTask.mockImplementation(async (id: string, input: object) => ({ task: task("pending", { id, ...input }) }));
    await show(<TaskBoard canManage isAgency />);
    await open("Post pending");
    await act(async () => { (host.querySelector("[data-drawer] form") as HTMLFormElement).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    const edit = crm.updateTask.mock.calls[0][1];
    for (const key of ["status", "visible_to_client", "needs_client_approval", "send_whatsapp"]) expect(edit).not.toHaveProperty(key);
    await open("Post pending");
    await click("Iniciar");
    expect(crm.transitionTask).toHaveBeenLastCalledWith("t-pending", "in_progress");
    await open("Post in_progress");
    await click("Concluir ✓");
    expect(crm.transitionTask).toHaveBeenLastCalledWith("t-in_progress", "completed");
  });

  it("cancelar preserva a tarefa e usa a rota auditável", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    crm.listCrmTasks.mockImplementation(async (status?: string) => ({ available: true,
      tasks: status === "completed" ? [] : [task("in_progress", { title: "Job de teste" })] }));
    await show(<TaskBoard canManage isAgency />);
    await open("Job de teste");
    await click("Cancelar tarefa");
    expect(confirm).toHaveBeenCalledWith('Cancelar a tarefa "Job de teste"? O histórico será preservado.');
    expect(crm.cancelTask).toHaveBeenCalledWith("t-in_progress");
    confirm.mockRestore();
  });

  it("hora sem data pede a data antes de salvar", async () => {
    await show(<TaskBoard canManage isAgency />);
    await click("+ Nova tarefa");
    const drawer = host.querySelector("[data-drawer]")!;
    await act(async () => {
      const title = drawer.querySelector("input[required]") as HTMLInputElement;
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(title, "Reunião");
      title.dispatchEvent(new Event("input", { bubbles: true }));
      const time = drawer.querySelector('input[type="time"]') as HTMLInputElement;
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(time, "10:00");
      time.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(drawer.textContent).toContain("Para usar a hora, escolha também a data do prazo.");
    await act(async () => { (drawer.querySelector("form") as HTMLFormElement).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(crm.createTask).not.toHaveBeenCalled();
  });
});

describe("estilo do quadro fora do Studio", () => {
  it("o próprio TaskBoard carrega o CSS (no Início não há tela do Studio para trazê-lo)", async () => {
    const { readFileSync } = await import("node:fs");
    const source = readFileSync(`${process.cwd()}/src/components/studio/TaskBoard.tsx`, "utf8");
    expect(source).toContain('import "../../styles/studio.css"');
    expect(readFileSync(`${process.cwd()}/src/styles/studio.css`, "utf8")).toContain(".taskBoard");
  });
});
