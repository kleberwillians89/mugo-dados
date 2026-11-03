// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const s = vi.hoisted(() => ({ contacts: [] as { id: string; name: string; phone: string; role: null; receives: string[]; is_primary: boolean }[], createContact: vi.fn(), sendForApproval: vi.fn() }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "c1", getActiveClientName: () => "Origami" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/studio/MeetingsStrip", () => ({ default: () => null }));
vi.mock("../app/media", async (o) => ({ ...(await o<object>()), getPlan: () => Promise.resolve(null) }));
vi.mock("../app/studio", async (o) => {
  const real = await o<typeof import("../app/studio")>();
  const now = new Date(); const next = new Date(now.getFullYear(), now.getMonth() + 1, 5, 12);
  const month = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}-01`;
  const item = { id: "i1", client_id: "c1", month, scheduled_at: next.toISOString(), format: "reels", title: "Bastidores", caption: "", status: "rascunho", origin: "manual" };
  return { ...real,
    getCalendar: () => Promise.resolve({ items: [item] }), getBrandProfile: () => Promise.resolve({ profile: null }),
    getProfileSuggestion: () => Promise.resolve({ suggestion: null }),
    listContacts: () => Promise.resolve({ contacts: s.contacts, whatsapp_channel: "mugozap" }),
    createContact: s.createContact, sendForApproval: s.sendForApproval };
});
import Calendar from "./Calendar";

let root: ReturnType<typeof createRoot>, node: HTMLDivElement;
beforeEach(() => {
  s.contacts = []; s.createContact.mockReset(); s.sendForApproval.mockReset();
  s.createContact.mockResolvedValue({ contact: { id: "new", name: "Kleber", phone: "5511972769605", role: null, receives: ["conteudo"], is_primary: true } });
  s.sendForApproval.mockResolvedValue({ request_id: "r1", link: "https://x/aprovar/t", whatsapp_url: "https://wa.me/x", whatsapp_text: "oi", whatsapp: { status: "enviado", text: "oi" } });
  node = document.createElement("div"); document.body.append(node); root = createRoot(node);
});
afterEach(() => { act(() => root.unmount()); node.remove(); });

const btn = (label: string) => [...document.querySelectorAll("button")].find((b) => b.textContent === label)!;
function type(label: string, value: string) {
  const input = [...document.querySelectorAll("label")].find((l) => l.textContent?.startsWith(label))!.querySelector("input")!;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true }));
}
async function openAndSend(name: string, phone: string) {
  await act(async () => root.render(<Calendar canManage isAgency />));
  await act(async () => btn("Enviar ao cliente").click());
  await act(async () => { type("Nome do contato", name); type("WhatsApp", phone); });
  await act(async () => { document.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
}

test("contato digitado na hora vira contato e a mensagem sai pelo WhatsApp da Mugô", async () => {
  await openAndSend("Kleber", "11972769605");
  expect(s.createContact).toHaveBeenCalledWith({ name: "Kleber", phone: "11972769605", receives: ["conteudo"], is_primary: true });
  expect(s.sendForApproval).toHaveBeenCalledWith(expect.objectContaining({ contact_id: "new", send_whatsapp: true }));
  expect(document.body.textContent).toContain("Enviado pelo WhatsApp da Mugô");
});

test("número que já é contato não duplica", async () => {
  s.contacts = [{ id: "old", name: "Ana", phone: "5511972769605", role: null, receives: ["financeiro"], is_primary: false }];
  await openAndSend("Kleber", "(11) 97276-9605");
  expect(s.createContact).not.toHaveBeenCalled();
  expect(s.sendForApproval).toHaveBeenCalledWith(expect.objectContaining({ contact_id: "old", send_whatsapp: true }));
});
