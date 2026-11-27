// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const data = vi.hoisted(() => ({ useDashboardSnapshot: vi.fn() }));
vi.mock("../../app/DashboardDataContext", () => data);
vi.mock("../data/DataFreshness", () => ({ DataFreshness: ({ provider }: { provider: string }) => <span>atualizado ({provider})</span> }));
import MediaKpiStrip from "./MediaKpiStrip";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

describe("Indicadores de mídia", () => {
  it("mostra a plataforma com dados, troca para a outra, indica fonte e leva à análise detalhada", async () => {
    data.useDashboardSnapshot.mockReturnValue({ loading: false, error: null, daily: [
      { meta_spend: 181.81, meta_link_clicks: 1936, meta_impressions: 64000, meta_purchases: 0, meta_attributed_revenue: 0 }] });
    const open = vi.fn();
    await act(async () => { root.render(<MediaKpiStrip onOpen={open} />); });
    expect(host.textContent).toContain("Investimento");
    expect(host.textContent).toContain("Cliques no link");
    expect(host.textContent).not.toContain("ROAS");
    expect(host.textContent).toContain("atualizado (meta_ads)");
    expect(host.textContent).toContain("Últimos 30 dias");
    await act(async () => { [...host.querySelectorAll("button")].find((b) => b.textContent === "Google Ads")!.click(); });
    expect(host.textContent).toContain("Sem dados de Google Ads neste período");
    await act(async () => { [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Abrir análise do Google"))!.click(); });
    expect(open).toHaveBeenCalledWith("google");
  });
});
