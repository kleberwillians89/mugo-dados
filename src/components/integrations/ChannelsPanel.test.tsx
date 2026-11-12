// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getChannels: vi.fn(), startChannel: vi.fn(), connectClarity: vi.fn(), syncChannel: vi.fn(), disconnectChannel: vi.fn() }));
vi.mock("../../app/channels", () => api);
import ChannelsPanel from "./ChannelsPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const totals = { spend: 80.5, impressions: 1500, clicks: 25, conversions: 3, days: 2, latest: null, top: [] };
const CH = [
  { provider: "tiktok_ads", label: "TikTok Ads", auth: "oauth", app_configured: true, status: "connected", account_name: "Conta 1", last_sync_at: "2026-11-12T12:00:00Z", last_error: null, metrics: { tiktok_ads: totals } },
  { provider: "tiktok", label: "TikTok orgânico", auth: "oauth", app_configured: false, status: "not_connected", account_name: null, last_sync_at: null, last_error: null, metrics: {} },
  { provider: "pinterest", label: "Pinterest", auth: "oauth", app_configured: true, status: "reauth_required", account_name: "@loja", last_sync_at: null, last_error: "Reconecte a conta.", metrics: {} },
  { provider: "clarity", label: "Microsoft Clarity", auth: "token", app_configured: true, status: "not_connected", account_name: null, last_sync_at: null, last_error: null, metrics: {} },
];
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });

async function mount(canManage = true) {
  api.getChannels.mockResolvedValue({ start: "2026-11-06", end: "2026-11-12", channels: CH });
  host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<ChannelsPanel canManage={canManage} />); });
  await act(async () => {});
  return root;
}

describe("ChannelsPanel", () => {
  it("mostra status, números e quem precisa reconectar", async () => {
    const root = await mount();
    expect(host.textContent).toContain("R$");
    expect(host.textContent).toContain("80,50");
    expect(host.textContent).toContain("Aguardando o app da plataforma");
    expect(host.textContent).toContain("Reconecte a conta.");
    const buttons = [...host.querySelectorAll("button")].map((b) => b.textContent);
    expect(buttons).toContain("Reconectar");
    act(() => root.unmount());
  });

  it("Clarity conecta com o token e recarrega", async () => {
    api.connectClarity.mockResolvedValue({ rows: 12 });
    const root = await mount();
    const open = [...host.querySelectorAll("button")].find((b) => b.textContent === "Conectar" && !b.hasAttribute("disabled") && b.closest("li")?.textContent?.includes("Clarity"))!;
    await act(async () => { open.click(); });
    const input = host.querySelector("input[type=password]") as HTMLInputElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(input, "x".repeat(40)); input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { (host.querySelector("form") as HTMLFormElement).requestSubmit(); });
    await act(async () => {});
    expect(api.connectClarity).toHaveBeenCalledWith("x".repeat(40), "");
    expect(host.textContent).toContain("Clarity conectado: 12 registros");
    act(() => root.unmount());
  });

  it("cliente vê os dados mas não os botões", async () => {
    const root = await mount(false);
    expect(host.querySelectorAll("button")).toHaveLength(0);
    act(() => root.unmount());
  });
});
