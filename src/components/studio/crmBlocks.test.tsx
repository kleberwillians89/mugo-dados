// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ listClientTasks: vi.fn(), listCrmConversations: vi.fn(), listCrmMessages: vi.fn() }));
vi.mock("../../app/crm", async (original) => ({ ...(await original<typeof import("../../app/crm")>()), ...state }));

import ClientTasks from "./ClientTasks";
import CrmConversations from "./CrmConversations";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };

describe("ClientTasks", () => {
  it("o cliente vê só as tarefas marcadas, sem o aviso interno", async () => {
    state.listClientTasks.mockResolvedValue({ available: true, tasks: [
      { id: "t1", title: "Gravar reels de novembro", status: "in_progress", due_date: null, updated_at: null },
    ] });
    await show(<ClientTasks isAgency={false} clientId="roove" />);
    expect(host.textContent).toContain("Gravar reels de novembro");
    expect(host.textContent).not.toContain("etiqueta");
  });

  it("sem tarefas, o bloco nem aparece para o cliente", async () => {
    state.listClientTasks.mockResolvedValue({ available: false, reason: "not_linked" });
    await show(<ClientTasks isAgency={false} clientId="roove" />);
    expect(host.textContent).toBe("");
  });

  it("a agência vê o aviso do que falta", async () => {
    state.listClientTasks.mockResolvedValue({ available: false, reason: "function_missing" });
    await show(<ClientTasks isAgency clientId="roove" />);
    expect(host.textContent).toContain("ponte do CRM ainda não foi publicada");
  });
});

describe("CrmConversations", () => {
  it("casa a conversa com o contato do Dados mesmo sem o 9º dígito", async () => {
    state.listCrmConversations.mockResolvedValue({ available: true, conversations: [{
      id: "c1", status: "open", attendance_mode: null, unread_count: 2, last_message_at: null, service_window_expires_at: null,
      contact: { name: "Ana", phone_masked: "•••• 1161", matched_phone: "551193161161" },
      last_message: { direction: "inbound", at: "2026-10-30T12:00:00Z", text: "Aprovado!" },
    }] });
    await show(<CrmConversations clientId="roove" contacts={[{ id: "k1", name: "Ana", phone: "5511993161161", role: null, receives: ["conteudo"], is_primary: true }]} />);
    expect(host.textContent).toContain("Aprovado!");
    expect(host.textContent).not.toContain("Outros contatos");
  });
});
