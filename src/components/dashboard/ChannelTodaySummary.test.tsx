// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import ChannelTodaySummary from "./ChannelTodaySummary";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

async function render(value: { revenue: number | null; orders: number | null } | null) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(<ChannelTodaySummary channel="Meta" date="2026-08-11" value={value} />));
}

describe("ChannelTodaySummary", () => {
  it("mostra apenas vendas, pedidos e ticket atribuídos do dia", async () => {
    await render({ revenue: 900, orders: 3 });
    expect(host.textContent).toContain("R$ 900,00");
    expect(host.textContent).toContain("R$ 300,00");
    expect(host.textContent).not.toContain("ROAS");
    expect(host.textContent).not.toContain("Investimento");
  });

  it("não converte ausência em zero", async () => {
    await render(null);
    expect(host.textContent).toContain("Sem dados atualizados");
    expect(host.textContent).not.toContain("R$ 0,00");
  });
});
