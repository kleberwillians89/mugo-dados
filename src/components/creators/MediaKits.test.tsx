// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ listMediaKits: vi.fn(), saveMediaKit: vi.fn(), uploadMediaKit: vi.fn() }));
vi.mock("../../app/creators", async (original) => ({ ...(await original<typeof import("../../app/creators")>()), ...api }));

import MediaKits from "./MediaKits";
import type { Creator } from "../../app/creators";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

const CREATOR = { id: "c1", network: "instagram", handle: "ana", followers: 12000, profile_url: null } as unknown as Creator;
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === label) as HTMLButtonElement | undefined;
const input = (label: string) => host.querySelector(`[aria-label="${label}"], label`) && ([...host.querySelectorAll("label")].find((l) => l.textContent?.startsWith(label))
  ?.querySelector("input,textarea") || host.querySelector(`[aria-label="${label}"]`)) as HTMLInputElement;
const type = async (el: HTMLInputElement, value: string) => {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); });
};
async function show(canAct = true) {
  await act(async () => { root.render(<MediaKits creators={[CREATOR]} canAct={canAct} />); });
  await act(async () => {});
}

describe("Mídia kit e valores", () => {
  it("salva e-mail, telefone e valores do criador", async () => {
    api.listMediaKits.mockResolvedValue({ kits: [] });
    api.saveMediaKit.mockImplementation(async (_id: string, kit: object) => ({ ...kit, creator_id: "c1" }));
    await show();
    await act(async () => { btn("Adicionar mídia kit")!.click(); });
    await type(input("E-mail"), "ana@x.com");
    await type(input("Telefone / WhatsApp"), "11 99999-0000");
    await act(async () => { btn("+ Valor")!.click(); });
    await type(host.querySelector("[aria-label='Entregável']") as HTMLInputElement, "1 Reels");
    await type(host.querySelector("[aria-label='Valor']") as HTMLInputElement, "1.500,50");
    await act(async () => { btn("Salvar")!.click(); });
    expect(api.saveMediaKit).toHaveBeenCalledWith("c1", expect.objectContaining({
      email: "ana@x.com", phone: "11 99999-0000", deals: [], prices: [{ deliverable: "1 Reels", amount: 1500.5, notes: null }] }));
    expect(host.textContent).toContain("Mídia kit de @ana salvo");
  });

  it("'Fechado' registra o fechamento no histórico e já salva", async () => {
    api.listMediaKits.mockResolvedValue({ kits: [{ creator_id: "c1", files: [], prices: [], email: "ana@x.com", phone: null, contact: null, notes: null,
      deals: [{ id: "d0", closed_at: "2026-10-01", what: "Stories outubro", amount: 500 }] }] });
    api.saveMediaKit.mockImplementation(async (_id: string, kit: object) => ({ ...kit, creator_id: "c1" }));
    await show();
    expect(host.textContent).toContain("Fechado ✓ 01/10/2026");
    await act(async () => { btn("Ver e editar")!.click(); });
    await act(async () => { btn("Fechado ✓")!.click(); });
    await type(input("O que foi fechado"), "1 Reels Black Friday");
    await type(input("Valor (R$)"), "1800");
    await act(async () => { btn("Registrar fechamento")!.click(); });
    const sent = api.saveMediaKit.mock.calls[0][1];
    expect(sent.deals).toHaveLength(2);
    expect(sent.deals[0]).toMatchObject({ what: "1 Reels Black Friday", amount: 1800 });
    expect(sent.deals[1]).toMatchObject({ id: "d0", what: "Stories outubro" });  // histórico antigo fica
    expect(sent.email).toBe("ana@x.com");
    expect(host.textContent).toContain("Fechamento com @ana registrado");
  });

  it("quem só lê vê, mas não edita", async () => {
    api.listMediaKits.mockResolvedValue({ kits: [] });
    await show(false);
    await act(async () => { btn("Ver")!.click(); });
    expect(btn("Salvar")).toBeUndefined();
    expect(btn("Fechado ✓")).toBeUndefined();
    expect(input("E-mail").disabled).toBe(true);
  });
});
