// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getLiveRead: vi.fn() }));
vi.mock("../../app/metaAds", () => api);
import MediaLiveRead from "./MediaLiveRead";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

const READ = { checked_at: "2026-11-24T22:22:00Z", resumo: "Tráfego barato (R$ 0,09 por clique); alcance com CPM baixo.", proximos_passos: ["Criar remarketing com quem clicou"],
  campanhas: [
    { id: "a", campanha: "Post do Instagram: O clima", objetivo: "Tráfego para o site", veredito: "escalar", leitura: "Clique a R$ 0,09.", acao: "Subir para R$ 45/dia.",
      numeros: { investido: 181.81, cliques_no_link: 1936, cpc_link: 0.09, ctr_link_pct: 3.02 }, ultimos_7_dias: {}, sinais: [] },
    { id: "b", campanha: "RUAH | BF26 | Reconhecimento", objetivo: "Alcance", veredito: "manter", leitura: "103 mil pessoas.", acao: "Manter até a BF.",
      numeros: { investido: 162.49, alcance: 103904, cpm: 1.56, frequencia: 1.1 }, ultimos_7_dias: {}, sinais: ["no ar há 0 dia(s)"] },
  ] };

describe("Leitura da IA das campanhas no ar", () => {
  it("mostra cada campanha com os números do próprio objetivo e atualiza sob pedido", async () => {
    api.getLiveRead.mockResolvedValue(READ);
    await act(async () => { root.render(<MediaLiveRead />); }); await act(async () => {});
    expect(api.getLiveRead).toHaveBeenCalledWith(false);
    const traffic = host.querySelector('[data-campaign="a"]')!.textContent!;
    expect(traffic).toContain("Custo por clique");
    expect(traffic).not.toContain("ROAS");
    const reach = host.querySelector('[data-campaign="b"]')!.textContent!;
    expect(reach).toContain("CPM");
    expect(reach).toContain("103.904");
    expect(host.textContent).toContain("Criar remarketing com quem clicou");
    await act(async () => { [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Atualizar"))!.click(); });
    expect(api.getLiveRead).toHaveBeenLastCalledWith(true);
  });
});
