// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ listChat: vi.fn(), sendChat: vi.fn(), chatUnread: vi.fn(), listTimeline: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...state }));

import ClientHub from "./ClientHub";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  window.localStorage.clear();
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  state.chatUnread.mockResolvedValue({ unread: { cliente: 2, equipe: 1 } });
  state.listChat.mockResolvedValue({ messages: [{ id: "m1", channel: "cliente", author_side: "cliente", author_name: "Carelle", body: "Amei o post", item_id: null, item_title: null, created_at: "2026-11-05T10:00:00Z", mine: false }] });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };
const props = { canManage: true, isAgency: true, month: "2026-12", posts: [{ id: "p1", title: "Post A" }], onOpenItem: () => undefined, onChanged: () => undefined };

describe("ClientHub", () => {
  it("abre direto na conversa, sem botão, com contador de não lidas", async () => {
    await show(<ClientHub team {...props} />);
    expect(host.textContent).toContain("Amei o post");
    expect(host.textContent).toContain("Equipe (interno)");
    expect(host.querySelector(".hubBadge")?.textContent).toBe("3");
  });

  it("cliente não vê o canal interno da equipe nem contatos", async () => {
    await show(<ClientHub team={false} {...props} canManage={false} isAgency={false} />);
    expect(host.textContent).not.toContain("Equipe (interno)");
    expect(host.textContent).not.toContain("Contatos");
    expect(host.textContent).toContain("Linha do tempo");
  });

  it("envia mensagem citando um post", async () => {
    state.sendChat.mockResolvedValue({ ok: true, message: { id: "m2", channel: "cliente", author_side: "mugo", author_name: "Julia", body: "Ajustado", item_id: "p1", item_title: "Post A", created_at: "2026-11-05T11:00:00Z", mine: true } });
    await show(<ClientHub team {...props} />);
    const textarea = host.querySelector("textarea")!;
    const select = host.querySelector(".chatActions select") as HTMLSelectElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(textarea, "Ajustado"); textarea.dispatchEvent(new Event("input", { bubbles: true }));
      const sel = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
      sel.call(select, "p1"); select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => { (host.querySelector(".chatActions .ds-button") as HTMLButtonElement).click(); });
    expect(state.sendChat).toHaveBeenCalledWith("cliente", "Ajustado", "p1");
    expect(host.textContent).toContain("📌 Post A");
  });
});
