// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listGoogleCampaignDrafts: vi.fn(), createGoogleCampaignDraft: vi.fn(), updateGoogleCampaignDraft: vi.fn(),
  deleteGoogleCampaignDraft: vi.fn(), getGoogleCampaignPublicationContext: vi.fn(), publishGoogleCampaignDraft: vi.fn(),
}));
vi.mock("../../app/googleCampaignDrafts", async (original) => ({ ...(await original<typeof import("../../app/googleCampaignDrafts")>()), ...api }));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "tenant-a" }));
vi.mock("../Drawer", () => ({ default: () => null }));

import GoogleAdsPanel from "./GoogleAdsPanel";

const draft = { id: "d1", status: "rascunho", payload: { platform: "google_ads", name: "Search Luxo", objective: "vendas", type: "SEARCH",
  daily_budget: 50, start_date: "2099-11-20", end_date: "2099-11-30", final_url: "https://example.com",
  locations: ["Sao Paulo"], keywords: ["luxo"], headlines: ["Um", "Dois", "Tres"], descriptions: ["Descricao um", "Descricao dois"], notes: "",
  contains_eu_political_advertising: false },
  created_at: null, updated_at: null, publication_available: true, message: "" } as const;

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  api.listGoogleCampaignDrafts.mockResolvedValue({ drafts: [draft], publication_available: true });
  api.getGoogleCampaignPublicationContext.mockResolvedValue({ connection_id: "c1", account: "•••• 7890", customer_id_suffix: "7890" });
  api.publishGoogleCampaignDraft.mockResolvedValue({ draft: { ...draft, status: "publicada", ads_manager_url: "https://ads.google.com/aw/campaigns" } });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.clearAllMocks(); });

describe("Google Ads publication", () => {
  it("shows an explicit paused confirmation before publishing and then exposes the external link", async () => {
    await act(async () => { root.render(<GoogleAdsPanel />); });
    await act(async () => {});
    const button = [...host.querySelectorAll("button")].find((item) => item.textContent === "Criar pausada no Google") as HTMLButtonElement;
    await act(async () => { button.click(); });
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("serão criados PAUSADOS"));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("•••• 7890"));
    expect(api.publishGoogleCampaignDraft).toHaveBeenCalledWith("d1");
    expect(host.querySelector('a[href="https://ads.google.com/aw/campaigns"]')?.textContent).toBe("Abrir no Google Ads");
  });

  it("does not publish when the user cancels the confirmation", async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    await act(async () => { root.render(<GoogleAdsPanel />); });
    await act(async () => {});
    const button = [...host.querySelectorAll("button")].find((item) => item.textContent === "Criar pausada no Google") as HTMLButtonElement;
    await act(async () => { button.click(); });
    expect(api.publishGoogleCampaignDraft).not.toHaveBeenCalled();
  });
});
