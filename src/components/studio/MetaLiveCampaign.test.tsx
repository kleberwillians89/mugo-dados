// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdDraft, MetaLiveDeliveryStatus } from "../../app/metaAds";
import { deliverySummary } from "./metaLiveSummary";

const paused: MetaLiveDeliveryStatus = { draft_id: "d1", client_id: "roove", checked_at: "2026-11-19T13:00:00Z", source: "meta_graph", read_only: true,
  objects: { campaign_id: { id: "c", name: "", status: "PAUSED", effective_status: "PAUSED" }, ad_id: { id: "a", name: "", status: "ACTIVE", effective_status: "CAMPAIGN_PAUSED" } } };
const m = vi.hoisted(() => ({
  status: vi.fn(), results: vi.fn(), activate: vi.fn(), pause: vi.fn(),
}));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "roove" }));
vi.mock("../../app/metaAds", () => ({ readMetaLiveDeliveryStatus: m.status, readAdResults: m.results, activateAdDraft: m.activate, pauseAdDraft: m.pause }));
import MetaLiveCampaign from "./MetaLiveCampaign";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });
const draft = { id: "d1", status: "publicada", meta_ids: { campaign_id: "c" },
  payload: { name: "BF Roove", daily_budget: 50, start_date: "2026-11-20", end_date: "2026-11-30" } } as unknown as AdDraft;

describe("Campanha na Meta pelo painel", () => {
  it("resume o estado em linguagem simples", () => {
    expect(deliverySummary(paused).title).toBe("Pausada");
    const review = { ...paused, delivery: { state: "ativa" as const, by: "K", at: "" }, objects: { campaign_id: { id: "c", name: "", status: "ACTIVE", effective_status: "ACTIVE" }, ad_id: { id: "a", name: "", status: "ACTIVE", effective_status: "PENDING_REVIEW" } } };
    expect(deliverySummary(review).title).toBe("Ativada · em análise na Meta");
    const live = { ...review, objects: { ...review.objects, ad_id: { id: "a", name: "", status: "ACTIVE", effective_status: "ACTIVE" } } };
    expect(deliverySummary(live).tone).toBe("ok");
  });

  it("ativar pede confirmação da verba e do cliente antes de ligar", async () => {
    m.status.mockResolvedValue(paused);
    m.results.mockResolvedValue({ draft_id: "d1", period: "maximum", checked_at: "2026-11-19T13:00:00Z", currency: "BRL", spend: 0, impressions: 0, reach: 0,
      clicks: 0, link_clicks: 0, ctr: 0, cpc: null, results: 0, result_label: "Cadastros", cost_per_result: null, daily_budget: 50 });
    m.activate.mockResolvedValue({ ...paused, delivery: { state: "ativa", by: "Kleber", at: "2026-11-19T13:01:00Z" } });
    host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => createRoot(host).render(<MetaLiveCampaign draft={draft} adsCount={2} />));
    await act(async () => {});
    expect(host.textContent).toContain("Pausada");
    expect(host.textContent).toContain("nada gasto ainda");
    const button = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement;
    await act(async () => button("Ativar na Meta").click());
    expect(host.textContent).toMatch(/50,00 por dia/);
    expect(button("Ativar agora").disabled).toBe(true);
    await act(async () => (host.querySelector('.metaLiveConfirm input[type="checkbox"]') as HTMLInputElement).click());
    await act(async () => button("Ativar agora").click());
    expect(m.activate).toHaveBeenCalledWith("d1", 50);
    expect(button("Pausar")).toBeTruthy();
  });
});
