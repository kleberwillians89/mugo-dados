// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import StoreMediaSummary from "./StoreMediaSummary";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

async function render(channel: "Meta" | "Google", roasBasis: "attributed" | "shopify" = "attributed") {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(<StoreMediaSummary
    channel={channel}
    roasBasis={roasBasis}
    store={{ revenue: 1000, orders: 4, ticket: 250 }}
    media={{ spend: 100, roas: 3, attributedRevenue: 300, attributedOrders: 2 }}
  />));
}

describe("StoreMediaSummary", () => {
  it("separa resultado real Shopify de atribuição Meta", async () => {
    await render("Meta", "shopify");
    const store = host.querySelector(".is-store");
    const media = host.querySelector(".is-media");
    expect(store?.textContent).toContain("Receita realR$ 1.000,00Fonte: Shopify");
    expect(store?.textContent).toContain("Pedidos4Fonte: Shopify");
    expect(store?.textContent).toContain("Ticket médioR$ 250,00Fonte: Shopify");
    expect(media?.textContent).toContain("Investimento MetaR$ 100,00Fonte: Meta Ads");
    expect(media?.textContent).toContain("ROAS Meta3.00x");
    expect(media?.textContent).toContain("Receita real Shopify ÷ investimento");
    expect(media?.textContent).toContain("Receita atribuídaR$ 300,00");
  });

  it("separa resultado real Shopify de atribuição Google", async () => {
    await render("Google");
    expect(host.querySelector(".is-store")?.textContent).toContain("Fonte: Shopify");
    expect(host.querySelector(".is-media")?.textContent).toContain("Investimento GoogleR$ 100,00Fonte: Google Ads");
    expect(host.querySelector(".is-media")?.textContent).toContain("ROAS Google3.00x");
  });
});
