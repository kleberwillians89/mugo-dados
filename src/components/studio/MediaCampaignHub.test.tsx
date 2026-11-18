// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import MediaCampaignHub from "./MediaCampaignHub";
import type { Brief } from "../../app/briefs";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const brief: Brief = {
  id: "brief-roove-1", created_at: "2026-11-18T12:00:00Z", created_side: "mugo",
  status: "pronto", request: "Black Friday, grupo WhatsApp e captação de leads",
  brief: { title: "Black Friday Roove", summary: "Acesso antecipado aos cupons",
    audience: "Clientes interessados em Skinwear",
    media: { objective: "leads", budget: 200 }, key_message: "Cadastre-se antes da Black Friday" }
};
const callbacks = () => ({
  onSelect: vi.fn(), onRefresh: vi.fn(), onEditBrief: vi.fn(), onMeta: vi.fn(), onGoogle: vi.fn(),
});
let host: HTMLDivElement;
afterEach(() => host?.remove());

describe("Mídia On — central de campanhas e briefing", () => {
  it("exibe briefing já criado e permite iniciar Meta e Google com o mesmo contexto", async () => {
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host), events = callbacks();
    await act(async () => root.render(<MediaCampaignHub briefs={[brief]} selectedId={brief.id}
      loading={false} error={null} canManage busy={false} {...events} />));
    expect(host.textContent).toContain("Black Friday Roove");
    expect(host.textContent).toContain("R$");
    expect(host.textContent).toContain("200");
    const buttons = [...host.querySelectorAll("button")];
    await act(async () => buttons.find(b => b.textContent?.includes("Meta Ads"))?.click());
    await act(async () => buttons.find(b => b.textContent?.includes("Google Ads"))?.click());
    expect(events.onMeta).toHaveBeenCalledWith(brief);
    expect(events.onGoogle).toHaveBeenCalledWith(brief);
    act(() => root.unmount());
  });
  it("não oferece preparação acionável sem permissão", async () => {
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => root.render(<MediaCampaignHub briefs={[brief]} selectedId={brief.id}
      loading={false} error={null} canManage={false} busy={false} {...callbacks()} />));
    const campaignButtons = [...host.querySelectorAll("button")].filter(b =>
      b.textContent?.includes("Meta Ads") || b.textContent?.includes("Google Ads"));
    expect(campaignButtons).toHaveLength(2);
    expect(campaignButtons.every(b => b.disabled)).toBe(true);
    act(() => root.unmount());
  });
});
