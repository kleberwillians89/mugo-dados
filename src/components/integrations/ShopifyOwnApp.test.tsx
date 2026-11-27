// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ readShopifyOwnApps: vi.fn(), saveShopifyOwnApp: vi.fn() }));
vi.mock("../../app/onboardingApi", async (original) => ({ ...(await original<typeof import("../../app/onboardingApi")>()), ...api }));
import ShopifyOwnApp from "./ShopifyOwnApp";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const type = async (label: string, value: string) => {
  const input = host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
  await act(async () => { input.dispatchEvent(new Event("input", { bubbles: true })); });
};

describe("App Shopify da loja", () => {
  it("salva o app da Ruah, limpa o segredo da tela e só mostra o fim do Client ID", async () => {
    api.readShopifyOwnApps.mockResolvedValue({ apps: [] });
    api.saveShopifyOwnApp.mockResolvedValue({ apps: [{ shop_domain: "ruah-parfums.myshopify.com", client_id_hint: "...123456", updated_at: null }] });
    await act(async () => { root.render(<ShopifyOwnApp shopDomain="ruah-parfums.myshopify.com" />); });
    expect(host.textContent).toContain("usando o app padrão");
    await type("Client ID", "ruah-app-client-123456");
    await type("Client Secret", "shpss_segredo_da_ruah_123");
    await act(async () => { ([...host.querySelectorAll("button")].find((b) => b.textContent === "Salvar app da loja") as HTMLButtonElement).click(); });
    expect(api.saveShopifyOwnApp).toHaveBeenCalledWith({ shop_domain: "ruah-parfums.myshopify.com", app_client_id: "ruah-app-client-123456", client_secret: "shpss_segredo_da_ruah_123" });
    expect((host.querySelector('[aria-label="Client Secret"]') as HTMLInputElement).value).toBe("");
    expect(host.textContent).toContain("ruah-parfums.myshopify.com (...123456)");
    expect(host.textContent).not.toContain("shpss_");
  });
});
