// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const studio = vi.hoisted(() => ({ chatUnread: vi.fn(), listTimeline: vi.fn(), listChat: vi.fn(), sendChat: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));

import ChatWidget, { newDone } from "./ChatWidget";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
const published = { id: "p-1", at: "2026-11-05T18:40:00Z", side: "mugo", kind: "publicado", text: "Publicado no Instagram: “Seu treino não é aleatório”", detail: null, item_id: "1", link: "https://instagram.com/p/x" };
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  studio.listChat.mockResolvedValue({ messages: [] });
  studio.listTimeline.mockResolvedValue({ events: [published, { id: "t-1", at: "2026-11-05T10:00:00Z", side: "cliente", kind: "aprovado", text: "x", detail: null, item_id: null }] });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); await act(async () => {}); };

describe("ChatWidget", () => {
  it("conta só o que a equipe fez depois da última olhada", () => {
    expect(newDone([published as never], "")).toBe(1);
    expect(newDone([published as never], "2026-11-06T00:00:00Z")).toBe(0);
  });

  it("cliente: abre sozinho com o que foi feito quando há novidade, uma vez por sessão", async () => {
    studio.chatUnread.mockResolvedValue({ unread: { cliente: 0 } });
    await show(<ChatWidget clientId="m2" team={false} />);
    expect(host.textContent).toContain("Publicado no Instagram");
    expect(host.textContent).toContain("ver no Instagram");
    expect(host.textContent).not.toContain("Só equipe");
    expect(localStorage.getItem("mugo.widget.seen.m2")).toBe(published.at);
    await act(async () => { root.render(<></>); });
    await show(<ChatWidget clientId="m2" team={false} />);
    expect(host.querySelector(".cwPanel")).toBeNull();
  });

  it("cliente com mensagem nova abre na conversa", async () => {
    studio.chatUnread.mockResolvedValue({ unread: { cliente: 2 } });
    await show(<ChatWidget clientId="latinas" team={false} />);
    expect(host.querySelector(".cwTabs .is-active")?.textContent).toContain("Conversa");
  });

  it("equipe não abre sozinho, só mostra o contador", async () => {
    studio.chatUnread.mockResolvedValue({ unread: { cliente: 2, equipe: 1 } });
    await show(<ChatWidget clientId="m2" team />);
    expect(host.querySelector(".cwPanel")).toBeNull();
    expect(host.querySelector(".cwBadge")?.textContent).toBe("4");
  });
});
