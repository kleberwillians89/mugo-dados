// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ConversationHistory from "./ConversationHistory";
import * as api from "../../app/api";
import type { IntelligenceConversation } from "../../app/intelligenceTypes";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("../../app/api", () => ({ getIntelligenceConversations: vi.fn(), getIntelligenceMessages: vi.fn(), createIntelligenceConversation: vi.fn(), resumeIntelligenceConversation: vi.fn(), renameIntelligenceConversation: vi.fn(), deleteIntelligenceConversation: vi.fn() }));
const row: IntelligenceConversation = { id: "thread", client_id: "tenant-a", user_id: "user-a", title: "Conversa salva", created_at: "2026-01-01", updated_at: "2026-01-01" };
const messages = [{ id: "question", role: "user" as const, content: { question: "Como estão as vendas?" }, period_start: "2026-01-01", period_end: "2026-01-07", created_at: "2026-01-07", sources: [] }];
let container: HTMLDivElement, root: ReturnType<typeof createRoot>;
let restore: ReturnType<typeof vi.fn>, loading: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.mocked(api.getIntelligenceConversations).mockReset().mockResolvedValue({ ok: true, items: [row], has_more: false });
  vi.mocked(api.getIntelligenceMessages).mockReset().mockResolvedValue({ ok: true, conversation: row, messages });
  vi.mocked(api.createIntelligenceConversation).mockReset().mockResolvedValue({ ok: true, conversation: { ...row, id: "new-thread", title: "Nova conversa" } });
  vi.mocked(api.resumeIntelligenceConversation).mockReset().mockResolvedValue({ ok: true });
  vi.mocked(api.renameIntelligenceConversation).mockReset().mockResolvedValue({ ok: true, conversation: { ...row, title: "Título corrigido" } });
  vi.mocked(api.deleteIntelligenceConversation).mockReset().mockResolvedValue({ ok: true });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container); restore = vi.fn(); loading = vi.fn();
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
async function render(client = "tenant-a", user = "user-a", activeId: string | null = null, busy = false) {
  await act(async () => { root.render(<ConversationHistory key={`${client}:${user}`} clientId={client} userId={user} activeId={activeId} busy={busy} revision="" onRestore={restore} onLoadingChange={loading} />); });
}
function button(text: string) { return [...container.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent === text)!; }

describe("Continuidade — histórico privado persistido", () => {
  it("restaura última conversa e pergunta ao montar, sem criar conversa nem chamar geração", async () => {
    await render();
    expect(api.getIntelligenceConversations).toHaveBeenCalledWith(0, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(restore).toHaveBeenCalledWith("thread", messages);
    expect(api.createIntelligenceConversation).not.toHaveBeenCalled(); expect(api.resumeIntelligenceConversation).not.toHaveBeenCalled();
    expect(loading).toHaveBeenLastCalledWith(false);
  });
  it("não restaura respostas de outro tenant nem de outro usuário", async () => {
    vi.mocked(api.getIntelligenceMessages).mockResolvedValueOnce({ ok: true, conversation: { ...row, user_id: "user-b" }, messages });
    await render(); expect(restore).not.toHaveBeenCalled(); expect(container.querySelector('[role="alert"]')).not.toBeNull();
    vi.mocked(api.getIntelligenceConversations).mockResolvedValueOnce({ ok: true, items: [{ ...row, client_id: "tenant-b" }], has_more: false });
    await render("tenant-b", "user-b"); expect(restore).not.toHaveBeenCalled();
  });
  it("nova conversa é persistida vazia antes de exibir novo estado", async () => {
    await render(); restore.mockClear(); await act(async () => button("Nova conversa").click());
    expect(api.createIntelligenceConversation).toHaveBeenCalledTimes(1);
    expect(restore).toHaveBeenCalledWith("new-thread", []);
  });
  it("retomar conversa antiga persiste seleção sem IA", async () => {
    await render(); restore.mockClear(); await act(async () => button("Conversa salva").click());
    expect(api.resumeIntelligenceConversation).toHaveBeenCalledWith("thread", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(restore).toHaveBeenCalledWith("thread", messages);
  });
  it("renomeia sem alterar conteúdo das respostas", async () => {
    await render(); await act(async () => button("Renomear").click());
    const input = container.querySelector("input")!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "Título corrigido"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(api.renameIntelligenceConversation).toHaveBeenCalledWith("thread", "Título corrigido", expect.anything());
    expect(container.textContent).toContain("Título corrigido");
  });
  it("excluir exige confirmação e limpa conversa ativa apenas após sucesso", async () => {
    await render("tenant-a", "user-a", "thread"); restore.mockClear();
    await act(async () => button("Excluir").click()); expect(api.deleteIntelligenceConversation).not.toHaveBeenCalled();
    await act(async () => button("Confirmar exclusão").click());
    expect(api.deleteIntelligenceConversation).toHaveBeenCalledWith("thread", expect.anything()); expect(restore).toHaveBeenCalledWith("", []);
    expect(container.textContent).not.toContain("Conversa salva");
  });
  it("falha de exclusão preserva conversa e histórico", async () => {
    await render("tenant-a", "user-a", "thread"); restore.mockClear(); vi.mocked(api.deleteIntelligenceConversation).mockRejectedValueOnce(new Error("private"));
    await act(async () => button("Excluir").click()); await act(async () => button("Confirmar exclusão").click());
    expect(restore).not.toHaveBeenCalled(); expect(container.textContent).toContain("Conversa salva"); expect(container.textContent).not.toContain("private");
  });
  it("troca de usuário aborta restauração anterior e rejeita resposta atrasada", async () => {
    let finish!: (value: Awaited<ReturnType<typeof api.getIntelligenceConversations>>) => void;
    vi.mocked(api.getIntelligenceConversations).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await render(); const signal = vi.mocked(api.getIntelligenceConversations).mock.calls[0][1]!.signal;
    vi.mocked(api.getIntelligenceConversations).mockResolvedValueOnce({ ok: true, items: [], has_more: false });
    await render("tenant-a", "user-b"); expect(signal?.aborted).toBe(true);
    await act(async () => finish({ ok: true, items: [row], has_more: false }));
    expect(restore).not.toHaveBeenCalled(); expect(container.textContent).not.toContain("Conversa salva");
  });
  it("pagina metadados e bloqueia mutações durante pergunta em execução", async () => {
    vi.mocked(api.getIntelligenceConversations).mockResolvedValueOnce({ ok: true, items: [row], has_more: true });
    await render(); vi.mocked(api.getIntelligenceConversations).mockResolvedValueOnce({ ok: true, items: [{ ...row, id: "older", title: "Conversa anterior" }], has_more: false });
    await act(async () => button("Carregar mais conversas").click());
    expect(api.getIntelligenceConversations).toHaveBeenLastCalledWith(1, expect.anything()); expect(container.textContent).toContain("Conversa anterior");
    await render("tenant-a", "user-a", "thread", true); expect(button("Nova conversa").disabled).toBe(true);
  });
});
