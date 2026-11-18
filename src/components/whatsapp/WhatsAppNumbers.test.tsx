// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const api = vi.hoisted(() => ({ listWhatsAppNumbers: vi.fn(), getWhatsAppConnectionStatus: vi.fn(), connectWhatsAppNumber: vi.fn(), disconnectWhatsAppNumber: vi.fn(), getRooveMetaRegistrationStatus: vi.fn(), registerRooveMetaNumber: vi.fn(), requestRooveMetaCode: vi.fn(), verifyRooveMetaCode: vi.fn() }));
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
    api.getWhatsAppConnectionStatus.mockResolvedValue({ ok: true, provider: "not_connected", native_connected: false, crm_bridge_configured: false, meta_credentials_saved: false, number_count: 0, numbers: [], notice: "Conecte o número.", requires_meta_credentials: true });
    api.connectWhatsAppNumber.mockResolvedValue({ ok: true, number: { id: "n1", waba_id: "1", phone_number_id: "2", display_phone_number: "+55 11 99316-1161", verified_name: "Roove", status: "active", subscribed_at: "2026-11-10T12:00:00Z", created_at: null } });
    const onChange = vi.fn();
    await act(async () => root.render(<WhatsAppNumbers onChange={onChange} />));
    await flush();
    await act(async () => (container.querySelector(".waPrimary") as HTMLButtonElement).click());
    const [waba, phone, metaAppId, token] = [...container.querySelectorAll("input")] as HTMLInputElement[];
    await act(async () => { type(waba, "112233445566778"); type(phone, "109876543210987"); type(metaAppId, "1161210926623351"); type(token, "EAAG-token-secreto-1234567890"); });
    await act(async () => (container.querySelector("form") as HTMLFormElement).requestSubmit());
    await flush();
    expect(api.connectWhatsAppNumber).toHaveBeenCalledWith({ waba_id: "112233445566778", phone_number_id: "109876543210987", access_token: "EAAG-token-secreto-1234567890", meta_app_id: "1161210926623351" });
    expect(container.textContent).toContain("+55 11 99316-1161");
    expect(container.textContent).not.toContain("EAAG-token");
    expect(onChange).toHaveBeenCalled();
  });
  it("consulta status Meta sem registrar automaticamente e exige confirmação", async () => {
    const roove = { id: "00000000-0000-4000-8000-000000000001", phone_number_id: "1063683626819387",
      meta_app_id: "1161210926623351", display_phone_number: "+55 11 94470-6392", status: "active", subscribed_at: null };
    api.listWhatsAppNumbers.mockResolvedValue({ ok: true, numbers: [roove] });
    api.getWhatsAppConnectionStatus.mockResolvedValue({ ok: true, provider: "native", native_connected: true, connected: true,
      crm_bridge_configured: false, meta_credentials_saved: true, number_count: 1, numbers: [roove], notice: "Cadastrado" });
    api.getRooveMetaRegistrationStatus.mockResolvedValue({ ok: true, status: "OFFLINE", can_register: true,
      registered: false, code_verification_status: "VERIFIED", registered_by_this_request: false });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await act(async () => root.render(<WhatsAppNumbers />));
    await flush();
    const statusButton = [...container.querySelectorAll("button")].find((x) => x.textContent?.includes("Consultar status na Meta"))!;
    await act(async () => statusButton.click());
    await flush();
    expect(api.getRooveMetaRegistrationStatus).toHaveBeenCalledWith(roove.id);
    expect(api.registerRooveMetaNumber).not.toHaveBeenCalled();
    expect(container.textContent).toContain("OFFLINE");
    const pin = container.querySelector('input[type="password"]') as HTMLInputElement;
    await act(async () => type(pin, "123456"));
    await act(async () => (pin.closest("form") as HTMLFormElement).requestSubmit());
    await flush();
    expect(confirm).toHaveBeenCalled();
    expect(api.registerRooveMetaNumber).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("não mostra ativação de Roove para outro número", async () => {
    api.listWhatsAppNumbers.mockResolvedValue({ ok: true, numbers: [{ id: "n2", phone_number_id: "99999",
      meta_app_id: null, display_phone_number: "+55 11 97485-8863", status: "active" }] });
    api.getWhatsAppConnectionStatus.mockResolvedValue({ ok: true, provider: "native", native_connected: true,
      connected: true, crm_bridge_configured: false, meta_credentials_saved: true, number_count: 1,
      notice: "Cadastrado" });
    await act(async () => root.render(<WhatsAppNumbers />));
    await flush();
    expect(container.textContent).not.toContain("Consultar status na Meta");
    expect(api.registerRooveMetaNumber).not.toHaveBeenCalled();
  });

  it("solicita OTP somente com confirmação e valida o código informado", async () => {
    const number = { id: "00000000-0000-4000-8000-000000000001", phone_number_id: "1063683626819387",
      meta_app_id: "1161210926623351", display_phone_number: "+55 11 94470-6392", status: "active", subscribed_at: null };
    api.listWhatsAppNumbers.mockResolvedValue({ numbers: [number] });
    api.getWhatsAppConnectionStatus.mockResolvedValue({ provider: "native", native_connected: true, connected: true,
      number_count: 1, notice: "Cadastrado" });
    api.getRooveMetaRegistrationStatus.mockResolvedValue({ ok: true, status: "DISCONNECTED",
      code_verification_status: "EXPIRED", registered: false, can_register: false, registered_by_this_request: false });
    api.requestRooveMetaCode.mockResolvedValue({ ok: true, requested: true, method: "SMS" });
    api.verifyRooveMetaCode.mockResolvedValue({ ok: true, verified: true });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await act(async () => root.render(<WhatsAppNumbers />));
    await flush();
    await act(async () => [...container.querySelectorAll("button")].find((b) => b.textContent?.includes("Consultar status na Meta"))!.click());
    await flush();
    const smsButton = [...container.querySelectorAll("button")].find((b) => b.textContent?.includes("Enviar código por SMS"))!;
    await act(async () => smsButton.click());
    await flush();
    expect(api.requestRooveMetaCode).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    await act(async () => smsButton.click());
    await flush();
    expect(api.requestRooveMetaCode).toHaveBeenCalledWith(number.id, "SMS", true);
    const otpInput = [...container.querySelectorAll('input[type="password"]')].find((x) => (x as HTMLInputElement).maxLength === 8) as HTMLInputElement;
    await act(async () => type(otpInput, "493821"));
    await act(async () => (otpInput.closest("form") as HTMLFormElement).requestSubmit());
    await flush();
    expect(api.verifyRooveMetaCode).toHaveBeenCalledWith(number.id, "493821", true);
    expect(container.textContent).not.toContain("493821");
    confirm.mockRestore();
  });

});
