// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const api = vi.hoisted(() => ({ listWhatsAppNumbers: vi.fn(), connectWhatsAppNumber: vi.fn(), disconnectWhatsAppNumber: vi.fn() }));
vi.mock("../../app/whatsapp", () => api);
import WhatsAppNumbers from "./WhatsAppNumbers";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => { Object.values(api).forEach((fn) => fn.mockReset()); container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); });
const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve(); }); };
const type = (input: HTMLInputElement, value: string) => {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
};

describe("Número de WhatsApp da marca", () => {
  it("some para quem não é da agência", async () => {
    api.listWhatsAppNumbers.mockRejectedValue(new Error("403"));
    await act(async () => root.render(<WhatsAppNumbers />));
    await flush();
    expect(container.textContent).toBe("");
  });

  it("liga o número e não mostra o token depois", async () => {
    api.listWhatsAppNumbers.mockResolvedValue({ ok: true, numbers: [] });
    api.connectWhatsAppNumber.mockResolvedValue({ ok: true, number: { id: "n1", waba_id: "1", phone_number_id: "2", display_phone_number: "+55 11 99316-1161", verified_name: "Roove", status: "active", subscribed_at: "2026-11-10T12:00:00Z", created_at: null } });
    const onChange = vi.fn();
    await act(async () => root.render(<WhatsAppNumbers onChange={onChange} />));
    await flush();
    await act(async () => (container.querySelector(".waPrimary") as HTMLButtonElement).click());
    const [waba, phone, token] = [...container.querySelectorAll("input")] as HTMLInputElement[];
    await act(async () => { type(waba, "112233445566778"); type(phone, "109876543210987"); type(token, "EAAG-token-secreto-1234567890"); });
    await act(async () => (container.querySelector("form") as HTMLFormElement).requestSubmit());
    await flush();
    expect(api.connectWhatsAppNumber).toHaveBeenCalledWith({ waba_id: "112233445566778", phone_number_id: "109876543210987", access_token: "EAAG-token-secreto-1234567890" });
    expect(container.textContent).toContain("+55 11 99316-1161");
    expect(container.textContent).not.toContain("EAAG-token");
    expect(onChange).toHaveBeenCalled();
  });
});
