// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const studio = vi.hoisted(() => ({ listChat: vi.fn(), sendChat: vi.fn(), chatUnread: vi.fn(), listTimeline: vi.fn(), getKnowledge: vi.fn() }));
const crm = vi.hoisted(() => ({ listCrmTasks: vi.fn(), listClientTasks: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));
vi.mock("../../app/crm", async (original) => ({ ...(await original<typeof import("../../app/crm")>()), ...crm }));

import ClientHub, { ago } from "./ClientHub";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
const recent = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
beforeEach(() => {
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  studio.chatUnread.mockResolvedValue({ unread: { cliente: 2, equipe: 1 } });
  studio.listChat.mockResolvedValue({ messages: [{ id: "m1", channel: "cliente", author_side: "cliente", author_name: "Carelle", body: "Amei o post", item_id: null, item_title: null, created_at: recent, mine: false }] });
  studio.listTimeline.mockResolvedValue({ events: [
    { id: "e1", at: recent, side: "cliente", kind: "ajuste_solicitado", text: "", actor: "Elis", title: "Cyber Monday", item_id: "p2", detail: "Trocar pela véspera do Dia do Forró", changes: [] },
    { id: "e2", at: recent, side: "mugo", kind: "pedido", text: "Mugô enviou 3 posts", detail: null, item_id: null }] });
  studio.getKnowledge.mockResolvedValue({ knowledge: "", sources: 3, updated_at: null, documents: [] });
  crm.listCrmTasks.mockResolvedValue({ available: true, tasks: [{ id: "t1", status: "pending", due_date: "2020-01-01" }, { id: "t2", status: "pending", due_date: null }] });
  crm.listClientTasks.mockResolvedValue({ available: true, tasks: [] });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); await act(async () => {}); };
const props = { canManage: true, isAgency: true, month: "2026-12", onOpenItem: vi.fn(), onChanged: () => undefined,
  posts: [{ id: "p1", title: "Post A", status: "aprovado" }, { id: "p2", title: "Cyber Monday", status: "rejeitado" }] };
const card = (label: string) => [...host.querySelectorAll<HTMLButtonElement>(".deskCard")].find((b) => b.textContent?.includes(label))!;

describe("ClientHub (resumo + gaveta)", () => {
  it("mostra os 4 cartões com o que pede atenção, sem abrir nada", async () => {
    await show(<ClientHub team {...props} />);
    expect(host.querySelectorAll(".deskCard")).toHaveLength(4);
    expect(card("Ajustes pedidos").textContent).toContain("1");
    expect(card("Ajustes pedidos").textContent).toContain("Elis");
    expect(card("Conversa").textContent).toContain("3 novas");
    expect(card("Tarefas").textContent).toContain("1 atrasada");
    expect(card("IA da marca").textContent).toContain("3 fontes");
    expect(document.body.textContent).not.toContain("Trocar pela véspera");
  });

  it("abre a gaveta de ajustes só com ações do cliente", async () => {
    await show(<ClientHub team {...props} />);
    await act(async () => { card("Ajustes pedidos").click(); });
    expect(document.body.textContent).toContain("Trocar pela véspera do Dia do Forró");
    expect(document.body.textContent).not.toContain("Mugô enviou 3 posts");
    const open = [...document.querySelectorAll<HTMLButtonElement>(".deskItem button")].find((b) => b.textContent === "Abrir post")!;
    await act(async () => { open.click(); });
    expect(props.onOpenItem).toHaveBeenCalledWith("p2");
  });

  it("cliente não vê canal interno nem contatos", async () => {
    await show(<ClientHub team={false} {...props} canManage={false} isAgency={false} />);
    await act(async () => { card("Conversa").click(); });
    expect(document.body.textContent).not.toContain("Só equipe");
    expect(document.body.textContent).not.toContain("Mais");
    expect(crm.listCrmTasks).not.toHaveBeenCalled();
  });

  it("tempo relativo curto", () => {
    const now = Date.parse("2026-11-05T12:00:00Z");
    expect(ago("2026-11-05T11:58:00Z", now)).toBe("há 2 min");
    expect(ago("2026-11-05T09:00:00Z", now)).toBe("há 3 h");
  });
});
