// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const email = vi.hoisted(() => ({ listCampaigns: vi.fn(async () => ({ campaigns: [] })), createCampaign: vi.fn(), getCampaign: vi.fn(() => new Promise(() => {})),
  listRelationshipLists: vi.fn(async () => ({ lists: [] })) }));
vi.mock("../../app/emailMarketing", async (original) => ({ ...(await original<typeof import("../../app/emailMarketing")>()), ...email }));
const work = vi.hoisted(() => ({ listWorkTasks: vi.fn(), getTaskContext: vi.fn(), createEmailFromTask: vi.fn() }));
vi.mock("../../app/taskWork", async (original) => ({ ...(await original<typeof import("../../app/taskWork")>()), ...work }));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "curavino", getActiveClientName: () => "Curavino" }));

import CampaignsPanel from "./CampaignsPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const TASK = { id: "t1", title: "Redator: Black November", status: "pending", due_date: "2026-11-30", category: "Redator", assignees: ["Ana"] };
const CTX = {
  client_id: "curavino", client_name: "Curavino",
  task: { id: "t1", title: "Redator: Black November", status: "pending", due_date: "2026-11-30", category: "Redator", deliverable_url: null },
  brief_id: "b1", source: "briefing", module: "email_marketing", links: [], existing: [],
  context: { title: "Black November: até 50% off em vinhos", objective: "Aumentar pedidos", key_message: "Até 50% off",
    audience: "Vinhos naturais e orgânicos", deliverables: ["E-mails promocionais", "Legendas"], avoid: ["Não prometer descontos superiores a 50%"],
    your_part: "Produzir textos para e-mails", notes: "" },
  deliverables_for_module: ["E-mails promocionais"], suggested_deliverable: "E-mails promocionais",
};
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  work.listWorkTasks.mockResolvedValue({ available: true, client_name: "Curavino", tasks: [TASK] });
  work.getTaskContext.mockResolvedValue(CTX);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const flush = async () => { await act(async () => {}); await act(async () => {}); };
const button = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes(label)) as HTMLButtonElement;

describe("E-mail Marketing a partir do Kanban (Black November)", () => {
  async function pickTask() {
    await act(async () => { root.render(<CampaignsPanel canEdit />); }); await flush();
    await act(async () => { button("Nova campanha").click(); });
    await act(async () => { button("Selecionar tarefa do Kanban").click(); }); await flush();
    expect(host.textContent).toContain("Selecionar tarefa do Kanban · Curavino");
    await act(async () => { button("Redator: Black November").click(); }); await flush();
  }

  it("mostra o briefing legível e o entregável de e-mail já sugerido", async () => {
    await pickTask();
    expect(work.getTaskContext).toHaveBeenCalledWith("t1", "email_marketing");
    expect(host.textContent).toContain("Restrições");
    expect(host.textContent).toContain("Não prometer descontos superiores a 50%");
    expect(host.textContent).toContain("Sua parte");
    const radios = [...host.querySelectorAll<HTMLInputElement>('input[type="radio"]')];
    expect(radios[0].checked).toBe(true);
    expect(radios[0].parentElement?.textContent).toContain("E-mails promocionais");
    expect(host.textContent).not.toContain("Legendas"); // entregável de outro módulo não aparece como opção
  });

  it("cria o rascunho com o briefing e abre no editor", async () => {
    work.createEmailFromTask.mockResolvedValue({ created: { id: "c-new", name: "Black", status: "rascunho" }, existing: [] });
    await pickTask();
    await act(async () => { button("Criar conteúdo com este briefing").click(); }); await flush();
    expect(work.createEmailFromTask).toHaveBeenCalledWith("t1", { deliverable: "E-mails promocionais", mode: "ia", new_version: false });
    expect(email.getCampaign).toHaveBeenCalledWith("c-new");
  });

  it("tarefa que já tem campanha: oferece abrir em vez de duplicar", async () => {
    work.getTaskContext.mockResolvedValue({ ...CTX, existing: [{ id: "c-old", name: "Black v1", subject: "", status: "rascunho", deliverable: "E-mails promocionais" }] });
    await pickTask();
    expect(host.textContent).toContain("Esta tarefa já tem uma campanha de e-mail");
    expect(button("Criar conteúdo com este briefing")).toBeUndefined();
    await act(async () => { button("Abrir “Black v1”").click(); }); await flush();
    expect(email.getCampaign).toHaveBeenCalledWith("c-old");
    expect(work.createEmailFromTask).not.toHaveBeenCalled();
  });

  it("criar sem tarefa continua funcionando", async () => {
    email.createCampaign.mockResolvedValue({ campaign: { id: "c-free" } });
    await act(async () => { root.render(<CampaignsPanel canEdit />); }); await flush();
    await act(async () => { button("Nova campanha").click(); });
    await act(async () => { button("Criar sem tarefa").click(); }); await flush();
    expect(email.createCampaign).toHaveBeenCalledWith({});
    expect(work.listWorkTasks).not.toHaveBeenCalled();
  });
});
