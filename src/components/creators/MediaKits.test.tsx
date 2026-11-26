// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ saveMediaKit: vi.fn(), uploadMediaKit: vi.fn() }));
vi.mock("../../app/creators", async (original) => ({ ...(await original<typeof import("../../app/creators")>()), ...api }));

import MediaKits, { MediaKitModal } from "./MediaKits";
import type { Creator, MediaKit } from "../../app/creators";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

const CREATOR = { id: "c1", network: "instagram", handle: "ana", followers: 12000, profile_url: null } as unknown as Creator;
const btn = (label: string) => [...document.querySelectorAll("button")].find((b) => b.textContent?.trim() === label) as HTMLButtonElement | undefined;
const input = (label: string) => ([...document.querySelectorAll("label")].find((l) => l.textContent?.startsWith(label))
  ?.querySelector("input,textarea") || document.querySelector(`[aria-label="${label}"]`)) as HTMLInputElement;
const type = async (el: HTMLInputElement, value: string) => {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); });
};
const KIT = { creator_id: "c1", files: [], prices: [], email: "ana@x.com", phone: null, contact: null, notes: null,
  deals: [{ id: "d0", closed_at: "2026-10-01", what: "Stories outubro", amount: 500 }] } as MediaKit;
async function show(kit?: MediaKit, canAct = true, onSaved = vi.fn()) {
  await act(async () => { root.render(<MediaKitModal creator={CREATOR} kit={kit} canAct={canAct} onSaved={onSaved} onClose={() => undefined} />); });
  return onSaved;
}

describe("Mídia kit e valores", () => {
  it("CRM criadores: filtra por status, mostra valores e contatos, e troca o status", async () => {
    const onOpen = vi.fn(); const onStatus = vi.fn(async () => undefined);
    const other = { ...CREATOR, id: "c2", handle: "bia" } as Creator;
    const kits = { c1: { ...KIT, prices: [{ deliverable: "1 Reels", amount: 9000 }], phone: "11 99999-0000" }, c2: { ...KIT, creator_id: "c2", deals: [], status: "nao_fechou", status_note: "Sem verba" } } as Record<string, MediaKit>;
    await act(async () => { root.render(<MediaKits creators={[CREATOR, other]} kits={kits} loading={false} canAct onOpen={onOpen} onStatus={onStatus} />); });
    expect(host.textContent).toContain("CRM criadores · 2");
    expect(host.textContent).toMatch(/1 Reels: R\$\s9\.000,00/);
    expect(host.textContent).toContain("ana@x.com");
    expect(host.textContent).toContain("01/10/2026");
    expect(host.textContent).toContain("Sem verba");
    await act(async () => { btn("Não fechou · 1")!.click(); });
    expect(host.textContent).not.toContain("@ana");
    await act(async () => { btn("Todos · 2")!.click(); });
    const select = host.querySelector("select[aria-label='Status de @ana']") as HTMLSelectElement;
    expect(select.value).toBe("fechado");  // tinha fechamento
    await act(async () => { select.value = "negociando"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(onStatus).toHaveBeenCalledWith(CREATOR, "negociando");
    await act(async () => { btn("Abrir mídia kit")!.click(); });
    expect(onOpen).toHaveBeenCalledWith(CREATOR);
  });

  it("arrastar e soltar envia o mídia kit", async () => {
    api.uploadMediaKit.mockResolvedValue({ url: "https://x/kit.pdf", name: "kit.pdf", kind: "pdf" });
    await show();
    const zone = document.querySelector("[aria-label='Arraste o mídia kit aqui ou clique para escolher']") as HTMLElement;
    const file = new File(["%PDF"], "kit.pdf", { type: "application/pdf" });
    const drop = new Event("drop", { bubbles: true, cancelable: true }) as Event & { dataTransfer: unknown };
    Object.defineProperty(drop, "dataTransfer", { value: { files: [file] } });
    await act(async () => { zone.dispatchEvent(drop); });
    expect(api.uploadMediaKit).toHaveBeenCalledWith(file);
    expect(document.body.textContent).toContain("kit.pdf");
  });

  it("salva e-mail, telefone e valores do criador", async () => {
    api.saveMediaKit.mockImplementation(async (_id: string, kit: object) => ({ ...kit, creator_id: "c1" }));
    const onSaved = await show();
    await type(input("E-mail"), "ana@x.com");
    await type(input("Telefone / WhatsApp"), "11 99999-0000");
    await act(async () => { btn("+ Valor")!.click(); });
    await type(document.querySelector("[aria-label='Entregável']") as HTMLInputElement, "1 Reels");
    await type(document.querySelector("[aria-label='Valor']") as HTMLInputElement, "1.500,50");
    await act(async () => { btn("Salvar")!.click(); });
    expect(api.saveMediaKit).toHaveBeenCalledWith("c1", expect.objectContaining({
      email: "ana@x.com", phone: "11 99999-0000", deals: [], prices: [{ deliverable: "1 Reels", amount: 1500.5, notes: null }] }));
    expect(onSaved).toHaveBeenCalled();
    expect(document.body.textContent).toContain("Mídia kit salvo");
  });

  it("'Fechado' registra o fechamento no histórico e já salva", async () => {
    api.saveMediaKit.mockImplementation(async (_id: string, kit: object) => ({ ...kit, creator_id: "c1" }));
    await show(KIT);
    await act(async () => { btn("Fechado ✓")!.click(); });
    await type(input("O que foi fechado"), "1 Reels Black Friday");
    await type(input("Valor (R$)"), "1800");
    await act(async () => { btn("Registrar fechamento")!.click(); });
    const sent = api.saveMediaKit.mock.calls[0][1];
    expect(sent.deals).toHaveLength(2);
    expect(sent.deals[0]).toMatchObject({ what: "1 Reels Black Friday", amount: 1800 });
    expect(sent.status).toBe("fechado");  // registrar fechamento já marca Fechado no CRM
    expect(sent.deals[1]).toMatchObject({ id: "d0", what: "Stories outubro" });  // histórico antigo fica
    expect(sent.email).toBe("ana@x.com");
    expect(document.body.textContent).toContain("Fechamento com @ana registrado");
  });

  it("quem só lê vê, mas não edita", async () => {
    await show(KIT, false);
    expect(btn("Salvar")).toBeUndefined();
    expect(btn("Fechado ✓")).toBeUndefined();
    expect(input("E-mail").disabled).toBe(true);
  });
});
