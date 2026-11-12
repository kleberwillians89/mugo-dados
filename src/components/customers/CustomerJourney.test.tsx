// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getCustomerJourney: vi.fn(), rebuildCustomerJourney: vi.fn() }));
vi.mock("../../app/api", () => api);

const CustomerJourney = (await import("./CustomerJourney")).default;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BUILT = {
  ok: true,
  status: "ok",
  built_at: "2026-11-11T10:00:00Z",
  identities: ["external_id", "phone_key"],
  summary: { purchases: 2, revenue: 380, days_to_first_purchase: 3, channels: ["meta_ads", "whatsapp"], last_event_at: "2026-11-10T12:00:00Z" },
  events: [
    { event_key: "wa:1", kind: "conversa_whatsapp", at: "2026-11-01T12:00:00Z", source: "whatsapp", channel: "meta_ads", campaign: "Black Friday",
      ad_id: "ad9", value: null, evidence: "observado", detail: { origem: "Anúncio da Meta" } },
    { event_key: "order:1", kind: "pedido", at: "2026-11-04T12:00:00Z", source: "shopify", channel: "whatsapp", campaign: null, ad_id: null,
      value: 230, evidence: "regra", detail: { pedido: "#1001", depois_da_conversa: { em: "2026-11-01T12:00:00Z" } } },
    { event_key: "order:2", kind: "recompra", at: "2026-11-10T12:00:00Z", source: "shopify", channel: "meta_ads", campaign: "bf", ad_id: null,
      value: 150, evidence: "observado", detail: { pedido: "#1002" } },
  ],
};

let root: Root;
let host: HTMLDivElement;

async function render(canRebuild: boolean) {
  await act(async () => {
    root.render(<CustomerJourney customerId="pg1" canRebuild={canRebuild} />);
  });
}

describe("CustomerJourney", () => {
  beforeEach(() => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    api.getCustomerJourney.mockReset();
    api.rebuildCustomerJourney.mockReset();
  });
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  it("mostra a linha do tempo mais recente primeiro, com a evidência da ligação", async () => {
    api.getCustomerJourney.mockResolvedValue(BUILT);
    await render(false);
    const titles = [...host.querySelectorAll(".journeyTitle strong")].map((n) => n.textContent);
    expect(titles).toEqual(["Recompra", "Primeira compra", "Conversa no WhatsApp"]);
    expect(host.textContent).toContain("Ligado à conversa pela regra");
    expect(host.textContent).toContain("Meta Ads, WhatsApp");
    expect(host.textContent).toContain("Unido por cadastro da loja + telefone");
    expect(host.querySelector(".journeyRebuild")).toBeNull();
  });

  it("quem pode monta a jornada e a tela relê o resultado", async () => {
    api.getCustomerJourney.mockResolvedValueOnce({ ok: true, status: "not_built", events: [], summary: null, built_at: null })
      .mockResolvedValueOnce(BUILT);
    api.rebuildCustomerJourney.mockResolvedValue({ ok: true, built_at: "x", stats: {} });
    await render(true);
    expect(host.textContent).toContain("ainda não foi montada");
    const button = host.querySelector<HTMLButtonElement>(".journeyRebuild")!;
    expect(button.textContent).toBe("Montar jornada");
    await act(async () => { button.click(); });
    expect(api.rebuildCustomerJourney).toHaveBeenCalledTimes(1);
    expect(host.querySelectorAll(".journeyEvent")).toHaveLength(3);
  });

  it("migração pendente não oferece montar", async () => {
    api.getCustomerJourney.mockResolvedValue({ ok: true, status: "not_built", events: [], summary: null, built_at: null, migration_pending: true });
    await render(true);
    expect(host.textContent).toContain("ainda não foi ativada");
    expect(host.textContent).not.toContain("Use “Montar jornada”");
  });
});
