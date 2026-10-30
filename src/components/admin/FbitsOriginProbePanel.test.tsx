// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({ getFbitsOriginProbe: vi.fn() }));
vi.mock("../../app/api", () => api);

import FbitsOriginProbePanel from "./FbitsOriginProbePanel";

const COMPANIES = [
  { id: "curavino", name: "Curavino LTDA", trade_name: "Curavino", status: "active" },
  { id: "roove", name: "Roove", status: "active" },
];

const SUMMARY = {
  pedidos_analisados: 3,
  veredito: "2 de 3 pedidos têm UTM em campos que o Mugoverso já lê. A captura vai funcionar.",
  origem_por_tipo: { utm: 2, none: 1 },
  canal_calculado: { paid_social: 2, unknown: 1 },
  campos_no_topo_encontrados: { origem: 3 },
  metadados_de_origem_encontrados: { utm_source: 2 },
  metadados_outras_chaves: {},
  outros_campos: {},
};

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  api.getFbitsOriginProbe.mockReset();
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function submit() {
  await act(async () => {
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

describe("FbitsOriginProbePanel", () => {
  it("roda o diagnóstico da empresa escolhida e mostra veredito e origem traduzida", async () => {
    api.getFbitsOriginProbe.mockResolvedValue({
      ok: true,
      resumo_lista: SUMMARY,
      resumo_detalhe: null,
      pedidos_lista: [{ pedidoId: 101, data: "2026-10-20T12:00:00Z", origem_calculada_pelo_mugo: {
        attribution_source: "utm", origin_channel: "paid_social", utm_campaign: "black-friday" } }],
      pedidos_detalhe: [],
      requisicoes_feitas: 2,
    });
    act(() => root.render(<FbitsOriginProbePanel companies={COMPANIES} />));
    await submit();

    expect(api.getFbitsOriginProbe).toHaveBeenCalledWith("curavino", { days: 14, orderId: "" });
    const text = container.textContent || "";
    expect(text).toContain("A captura vai funcionar");
    expect(text).toContain("Com UTM (campanha identificada)");
    expect(text).toContain("Mídia paga · redes sociais");
    expect(text).toContain("black-friday");
    expect(text).not.toContain("paid_social");
  });

  it("recusa número de pedido inválido sem chamar a API", async () => {
    act(() => root.render(<FbitsOriginProbePanel companies={COMPANIES} />));
    const input = container.querySelector("input")!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(input, "abc");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await submit();
    expect(api.getFbitsOriginProbe).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Informe apenas o número do pedido.");
  });

  it("mostra mensagem legível quando a empresa não tem FBITS", async () => {
    api.getFbitsOriginProbe.mockResolvedValue({ ok: false, code: "FBITS_CONNECTION_NOT_FOUND",
      message: "Nenhuma conexão FBITS encontrada para esta empresa." });
    act(() => root.render(<FbitsOriginProbePanel companies={COMPANIES} />));
    await submit();
    expect(container.textContent).toContain("Nenhuma conexão FBITS encontrada");
  });
});
