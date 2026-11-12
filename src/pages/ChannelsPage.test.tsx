// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getChannels: vi.fn() }));
vi.mock("../app/channels", () => api);
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "c1", getActiveClientName: () => "Curavino" }));
vi.mock("../app/PeriodContext", () => ({ usePeriod: () => ({ period: { start: "2026-11-01", end: "2026-11-12" } }) }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/data/PageHeader", () => ({ default: () => null }));
vi.mock("../components/data/PeriodSelector", () => ({ default: () => null }));
import ChannelsPage from "./ChannelsPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const totals = { spend: 80.5, impressions: 1500, clicks: 25, conversions: 3, days: 2, latest: null, top: [{ name: "Natal", value: 80.5 }] };

describe("TikTok, Pinterest e LinkedIn", () => {
  it("lê no período do calendário, mostra anúncios conectados e avisa quem falta", async () => {
    api.getChannels.mockResolvedValue({ start: "2026-11-01", end: "2026-11-12", channels: [
      { provider: "tiktok_ads", label: "TikTok Ads", auth: "oauth", app_configured: true, status: "connected", metrics: { tiktok_ads: totals } },
      { provider: "tiktok", label: "TikTok orgânico", auth: "oauth", app_configured: true, status: "connected", metrics: { tiktok: { ...totals, latest: { followers: 950, likes: 4000, videos: 12 }, top: [] } } },
      { provider: "pinterest", label: "Pinterest", auth: "oauth", app_configured: false, status: "not_connected", metrics: {} },
      { provider: "linkedin", label: "LinkedIn", auth: "oauth", app_configured: true, status: "not_connected", metrics: {} },
    ] });
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(<ChannelsPage />); }); await act(async () => {});
    expect(api.getChannels).toHaveBeenCalledWith({ start: "2026-11-01", end: "2026-11-12" });
    expect(host.textContent).toContain("80,50");
    expect(host.textContent).toContain("Natal");
    expect(host.textContent).toContain("950");
    expect(host.textContent).toContain("Aguardando o app da plataforma");
    expect(host.textContent).toContain("Ainda não conectado");
    act(() => root.unmount()); host.remove();
  });
});
