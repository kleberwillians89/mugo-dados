// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getMediaNow: vi.fn(), getLiveRead: vi.fn() }));
vi.mock("../../app/metaAds", async (original) => ({ ...(await original<typeof import("../../app/metaAds")>()), ...api }));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "roove" }));
import MediaNow from "./MediaNow";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const c = (id: string, extra = {}) => ({ id, canal: "Meta", campanha: `Campanha ${id}`, objetivo: "Vendas", investido: 900, investido_7d: 300,
  verba_diaria: 40, dias_no_ar: 12, fim: null, recomendavel: true, sinal: "bem", motivo: "Dentro do esperado para o objetivo.",
  resultado: { label: "compras", value: 30, cost_label: "custo por compra", cost: 30, roas: 4.2 }, ...extra });
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const flush = async () => { await act(async () => {}); await act(async () => {}); };

describe("Sua mídia agora", () => {
  it("só campanhas no ar, com o número do objetivo e o sinal", async () => {
    api.getMediaNow.mockResolvedValue({ campaigns: [c("1"), c("2", { sinal: "atencao", motivo: "Custo por compra 40% acima da média nos últimos 7 dias." })], spend_7d: 600 });
    await act(async () => { root.render(<MediaNow showRecommendations={false} />); }); await flush();
    expect(host.textContent).toContain("Campanha 1");
    expect(host.textContent).toContain("Custo por compra");
    expect(host.querySelector(".mediaNowList li")?.textContent).toContain("Campanha 2");
    expect(host.querySelector(".mediaNowSignal")?.hasAttribute("open")).toBe(false);
    expect(host.querySelector(".mediaNowSignal p")?.textContent).toContain("Custo por compra 40% acima");
    const attention = Array.from(host.querySelectorAll("button")).find((button) => button.textContent?.trim() === "Atenção 1");
    await act(async () => attention?.click());
    expect(host.querySelectorAll(".mediaNowList li")).toHaveLength(1);
    expect(host.querySelector(".mediaNowResultCount")?.textContent).toBe("1 de 2 campanhas");
    expect(host.querySelector(".mediaNowTotals dd.is-warn")?.textContent).toBe("1");
    expect(api.getLiveRead).not.toHaveBeenCalled(); // cliente: sem IA
  });

  it("recomendações: no máximo 3 e só de campanha com dado suficiente", async () => {
    api.getMediaNow.mockResolvedValue({ campaigns: [c("1"), c("2", { recomendavel: false })], spend_7d: 600 });
    api.getLiveRead.mockResolvedValue({ melhorias: [
      { id: "1", canal: "Meta", campanha: "Campanha 1", texto: "Trocar o criativo" }, { id: "2", canal: "Meta", campanha: "Campanha 2", texto: "Palpite cedo" },
      { id: "1", canal: "Meta", campanha: "Campanha 1", texto: "A" }, { id: "1", canal: "Meta", campanha: "Campanha 1", texto: "B" },
      { id: "1", canal: "Meta", campanha: "Campanha 1", texto: "C" }] });
    await act(async () => { root.render(<MediaNow showRecommendations />); }); await flush();
    const tips = [...host.querySelectorAll(".mediaNowTips li")].map((li) => li.textContent);
    expect(tips).toHaveLength(3);
    expect(tips.join(" ")).not.toContain("Palpite cedo");
  });

  it("nenhuma no ar: diz isso, sem palpite", async () => {
    api.getMediaNow.mockResolvedValue({ campaigns: [], spend_7d: 0 });
    await act(async () => { root.render(<MediaNow showRecommendations />); }); await flush();
    expect(host.textContent).toContain("Nenhuma campanha no ar agora.");
    expect(api.getLiveRead).not.toHaveBeenCalled();
  });
});
