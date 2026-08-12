// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import ChannelTodaySummary from "./ChannelTodaySummary";
import { coveredShopifyDay } from "./shopifyCoverage";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

afterEach(async () => {
  if (root) await act(async () => root.unmount());
  host?.remove();
});

async function render(value: { revenue: number | null; orders: number | null } | null) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(<ChannelTodaySummary date="2026-08-11" value={value} />));
}

describe("ChannelTodaySummary", () => {
  it("mantém Hoje Shopify preenchido mesmo sem qualquer métrica de mídia no dia", () => {
    expect(coveredShopifyDay("2026-08-11", "2026-08-11", { revenue: 646.52, orders: 1 })).toEqual({ revenue: 646.52, orders: 1 });
    expect(coveredShopifyDay("2026-08-10", "2026-08-11", { revenue: 646.52, orders: 1 })).toBeNull();
  });
  it("mostra apenas vendas, pedidos e ticket atribuídos do dia", async () => {
    await render({ revenue: 900, orders: 3 });
    expect(host.textContent).toContain("R$ 900,00");
    expect(host.textContent).toContain("R$ 300,00");
    expect(host.textContent).not.toContain("ROAS");
    expect(host.textContent).not.toContain("Investimento");
    expect(host.textContent).toContain("Fonte: Shopify");
  });

  it("não converte ausência em zero", async () => {
    await render(null);
    expect(host.textContent).toContain("Sem dados atualizados");
    expect(host.textContent).not.toContain("R$ 0,00");
  });
});
