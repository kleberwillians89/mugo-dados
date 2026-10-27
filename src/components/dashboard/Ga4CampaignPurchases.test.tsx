// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test } from "vitest";
import Ga4CampaignPurchases from "./Ga4CampaignPurchases";
import { formatGa4Investment, formatGa4Roas } from "./ga4CampaignFormat";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => { container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

test("sem evento purchase mostra estado vazio", async () => {
  await act(async () => root.render(<Ga4CampaignPurchases acquisition={{ channel_groups: [], has_purchases: false, notes: [] }} />));
  expect(container.querySelector('[data-testid="ga4-acquisition-empty"]')?.textContent).toContain("Sem eventos de compra");
  await act(async () => root.render(<Ga4CampaignPurchases acquisition={undefined} />));
  expect(container.querySelector('[data-testid="ga4-acquisition-empty"]')).not.toBeNull();
});

test("lista canais com compras, receita GA4, aviso e marca de canal estimado", async () => {
  await act(async () => root.render(<Ga4CampaignPurchases acquisition={{
    has_purchases: true,
    notes: ["A receita é a atribuída pelo GA4 e não é o faturamento confirmado do e-commerce."],
    channel_groups: [
      { channel_group: "Paid Shopping", channel_group_label: "Shopping pago", channel_group_source: "ga4", sessions: 1200, ecommerce_purchases: 14, purchase_revenue: 3500.5 },
      { channel_group: "Direct", channel_group_label: "Direto", channel_group_source: "derivado", sessions: 300, ecommerce_purchases: 2, purchase_revenue: 410 },
    ],
  }} />));
  const rows = [...container.querySelectorAll("tbody tr")].map((tr) => tr.textContent || "");
  expect(rows[0]).toContain("Shopping pago");
  expect(rows[0]).toContain("14");
  expect(rows[0]).toMatch(/3\.500,50/);
  expect(rows[1]).toContain("estimado");
  expect(container.textContent).toContain("não é o faturamento confirmado");
});

test("investimento e ROAS só aparecem com número", () => {
  expect(formatGa4Roas(null)).toBe("—");
  expect(formatGa4Roas(4)).toBe("4,00x");
  expect(formatGa4Investment({ investment: null })).toBe("—");
  expect(formatGa4Investment({ investment: 200 })).toMatch(/200,00/);
});
