// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import type { HealthIndex } from "../../app/brandHealth";

const pillar = (key: string, name: string, score: number | null, weight: number, effective: number, extra: Record<string, unknown> = {}) => ({
  key, name, hint: `${name} dica`, score, detail: `${name} detalhe`, change: null, reason: score == null ? `${name} sem dado` : null,
  weight, effective_weight: effective, ...extra,
});
const fixture: HealthIndex = {
  period: { start: "2026-10-12", end: "2026-11-10", previous_start: "2026-09-12", previous_end: "2026-10-11" },
  index: 66, label: "Atenção", coverage: 85,
  pillars: [pillar("conversa", "Conversa", 70, 30, 35.3), pillar("conversao", "Conversão em vendas", 60, 25, 29.4),
    pillar("atencao", "Atenção no Instagram", 68, 20, 23.5), pillar("presenca", "Presença na mídia", null, 15, 0),
    pillar("reputacao", "Reputação", 90, 10, 11.8)] as HealthIndex["pillars"],
  weights: { conversa: 30, conversao: 25, atencao: 20, presenca: 15, reputacao: 10 },
  default_weights: { conversa: 30, conversao: 25, atencao: 20, presenca: 15, reputacao: 10 },
  custom_weights: false, can_edit_weights: true,
};

vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "roove" }));
const getHealthIndex = vi.fn(async () => fixture);
const saveHealthWeights = vi.fn(async (weights: unknown) => ({ weights, custom: true }));
vi.mock("../../app/brandHealth", async (orig) => ({ ...(await orig<typeof import("../../app/brandHealth")>()),
  getHealthIndex: (q: unknown) => getHealthIndex(q), saveHealthWeights: (w: unknown) => saveHealthWeights(w) }));

import HealthIndexCard from "./HealthIndexCard";
import { weightShares } from "../../app/brandHealth";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("Índice de saúde MUGOVERSO", () => {
  it("pesos viram porcentagem do total", () => {
    expect(weightShares({ conversa: 50, conversao: 50, atencao: 0, presenca: 0, reputacao: 0 })).toEqual(
      { conversa: 50, conversao: 50, atencao: 0, presenca: 0, reputacao: 0 });
  });

  it("mostra a nota, os pilares (o sem dado com o motivo) e salva os pesos editados", async () => {
    const el = document.createElement("div");
    document.body.appendChild(el);
    const root = createRoot(el);
    await act(async () => { root.render(<HealthIndexCard start="2026-10-12" end="2026-11-10" />); });
    expect(el.textContent).toContain("66/100");
    expect(el.textContent).toContain("Atenção");
    expect(el.textContent).toContain("Presença na mídia sem dado");
    expect(el.textContent).toContain("fora da conta");
    expect(el.textContent).toContain("Calculado com 85% dos pesos");

    const edit = [...el.querySelectorAll("button")].find((b) => b.textContent === "Editar pesos")!;
    await act(async () => { edit.click(); });
    const slider = el.querySelector<HTMLInputElement>('input[aria-label="Peso de Conversa"]')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(slider, "70");
      slider.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(el.textContent).toContain("50%"); // 70 de 140
    const save = [...el.querySelectorAll("button")].find((b) => b.textContent === "Salvar pesos")!;
    await act(async () => { save.click(); });
    expect(saveHealthWeights).toHaveBeenCalledWith({ conversa: 70, conversao: 25, atencao: 20, presenca: 15, reputacao: 10 });
    expect(getHealthIndex).toHaveBeenCalledTimes(2); // recarrega a nota com os pesos novos
    act(() => root.unmount());
  });

  it("sem permissão, não mostra o botão de editar", async () => {
    getHealthIndex.mockResolvedValueOnce({ ...fixture, can_edit_weights: false });
    const el = document.createElement("div");
    const root = createRoot(el);
    await act(async () => { root.render(<HealthIndexCard start="2026-10-01" end="2026-10-31" />); });
    expect(el.textContent).not.toContain("Editar pesos");
    act(() => root.unmount());
  });
});
