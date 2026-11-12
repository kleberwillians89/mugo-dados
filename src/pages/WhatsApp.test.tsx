// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({ getWhatsAppInsights: vi.fn(), getWhatsAppInbox: vi.fn(), getWhatsAppMessages: vi.fn(), replyWhatsApp: vi.fn() }));
vi.mock("../app/whatsapp", async (original) => ({ ...(await original<typeof import("../app/whatsapp")>()), ...api }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "ruah", getActiveClientName: () => "Ruah Parfums" }));
vi.mock("../app/PeriodContext", () => ({ usePeriod: () => ({ period: { start: "2026-11-01", end: "2026-11-09" } }) }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => React.createElement("div", null, children) }));
vi.mock("../components/data/PeriodSelector", () => ({ default: () => null }));

import WhatsApp from "./WhatsApp";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
const flush = async () => { for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); }); };

const INSIGHTS = {
  ok: true, status: "available", provider: "shopify", period: { start: "2026-11-01", end: "2026-11-09" },
  attribution_label: "Venda conta para a conversa…", window_days: 7, notes: ["Venda conta para a conversa…"],
  totals: { conversations: 3, converted_conversations: 1, conversion_rate: 33.3, orders: 1, revenue: 389, store_revenue: 1000,
    share_of_store_revenue: 38.9, ad_spend: 400, cost_per_conversation: 200, cost_per_sale: 400, ads_roas: 0.97 },
  origins: [{ key: "ad", label: "Anúncio no Meta", conversations: 2, sales: 1, orders: 1, revenue: 389, share: 66.7 },
    { key: "link", label: "Link ou QR code", conversations: 1, sales: 0, orders: 0, revenue: 0, share: 33.3 }],
  ads: [{ ad_id: "111", ad_name: "Reels Kit BF", headline: "Kit BF", campaign_name: "BF26", spend: 300, conversations: 12, sales: 0,
    orders: 0, revenue: 0, cost_per_conversation: 25, cost_per_sale: null, roas: 0, verdict: { code: "talk_no_sale", label: "Muita conversa, pouca venda" } }],
  links: [{ code: "loja-qr", conversations: 1, sales: 0, revenue: 0 }],
  alerts: [{ ad_id: "111", text: "Reels Kit BF já gastou R$ 300,00 e gerou 0 venda(s) pelo WhatsApp." }],
};
const INBOX = { ok: true, status: "available", conversations: [
  { id: "c1", status: "open", attendance_mode: "bot", unread_count: 0, last_message_at: "2026-11-09T20:41:00Z", service_window_expires_at: null,
    contact: { name: "Mariana", phone_masked: "•••• 3307", first_seen_at: "2026-11-09T20:31:00Z" },
    origin: { bucket: "ad", label: "Anúncio · Kit BF", ad_headline: "Kit BF", entry_code: null, at: null },
    purchase: { orders: 1, revenue: 389, last_order: "#4417", last_order_at: "2026-11-09T20:45:00Z" },
    last_message: { direction: "in", at: "2026-11-09T20:41:00Z", text: "Já paguei!" } },
  { id: "c2", status: "open", attendance_mode: "human", unread_count: 2, last_message_at: "2026-11-09T20:12:00Z", service_window_expires_at: null,
    contact: { name: "Rafael", phone_masked: "•••• 1200", first_seen_at: "2026-11-09T20:00:00Z" },
    origin: { bucket: "link", label: "Link · loja-qr", ad_headline: null, entry_code: "loja-qr", at: null },
    purchase: null, last_message: { direction: "in", at: "2026-11-09T20:12:00Z", text: "Tem 50 ml?" } },
] };

describe("Página WhatsApp", () => {
  it("mostra números, origem, anúncios com leitura e a caixa de entrada com a venda", async () => {
    api.getWhatsAppInsights.mockResolvedValue(INSIGHTS);
    api.getWhatsAppInbox.mockResolvedValue(INBOX);
    api.getWhatsAppMessages.mockResolvedValue({ available: true, messages: [
      { id: "m1", direction: "in", type: "text", status: "received", text: "Oi! Ainda tem o kit?", template_name: null, at: "2026-11-09T20:31:00Z", read_at: null, failed: false, error_code: null },
      { id: "m2", direction: "out", type: "text", status: "read", text: "Tem sim!", template_name: null, at: "2026-11-09T20:32:00Z", read_at: "2026-11-09T20:33:00Z", failed: false, error_code: null },
    ] });
    await act(async () => root.render(<WhatsApp />));
    await flush();
    expect(api.getWhatsAppInsights).toHaveBeenCalledWith("2026-11-01", "2026-11-09");
    const text = container.textContent || "";
    expect(document.querySelector(".ds-pageEyebrow")).toBeNull();
    expect(text).toContain("Conversas novas");
    expect(text).toContain("Anúncio no Meta");
    expect(text).toContain("Muita conversa, pouca venda");
    expect(text).toContain("loja-qr");
    expect(text).toContain("Comprou");
    expect(text).toContain("Como essa venda aconteceu");
    expect(text).toContain("Pedido #4417");
    expect(api.getWhatsAppMessages).toHaveBeenCalledWith("c1");
    expect(container.querySelector(".waBubble.is-out")?.textContent).toContain("Tem sim!");
    expect(text).not.toMatch(/phone_key|5511/);
  });

  it("filtra conversas e avisa quando o número da marca não está ligado", async () => {
    api.getWhatsAppInsights.mockResolvedValue({ ...INSIGHTS, status: "no_brand_number", totals: undefined });
    api.getWhatsAppInbox.mockResolvedValue(INBOX);
    api.getWhatsAppMessages.mockResolvedValue({ available: true, messages: [] });
    await act(async () => root.render(<WhatsApp />));
    await flush();
    expect(container.textContent).toContain("O WhatsApp desta marca ainda não está ligado.");
    const bought = [...container.querySelectorAll(".waChips button")].find((b) => b.textContent === "Compraram") as HTMLButtonElement;
    await act(async () => bought.click());
    const names = [...container.querySelectorAll(".waConvTop b")].map((b) => b.textContent);
    expect(names).toEqual(["Mariana"]);
  });
});

describe("Página WhatsApp — troca rápida de conversa", () => {
  it("resposta atrasada da conversa anterior não aparece na conversa aberta", async () => {
    api.getWhatsAppInsights.mockResolvedValue(INSIGHTS);
    api.getWhatsAppInbox.mockResolvedValue(INBOX);
    let releaseFirst: (value: unknown) => void = () => {};
    api.getWhatsAppMessages.mockImplementation((id: string) => id === "c1"
      ? new Promise((resolve) => { releaseFirst = resolve; })
      : Promise.resolve({ available: true, messages: [{ id: "r1", direction: "in", type: "text", status: "received", text: "Mensagem do Rafael", template_name: null, at: "2026-11-09T20:12:00Z", read_at: null, failed: false, error_code: null }] }));
    await act(async () => root.render(<WhatsApp />));
    await flush();
    const rafael = [...container.querySelectorAll(".waConvList button")].find((b) => b.textContent?.includes("Rafael")) as HTMLButtonElement;
    await act(async () => rafael.click());
    await flush();
    await act(async () => releaseFirst({ available: true, messages: [{ id: "m1", direction: "in", type: "text", status: "received", text: "Mensagem da Mariana", template_name: null, at: "2026-11-09T20:31:00Z", read_at: null, failed: false, error_code: null }] }));
    await flush();
    const thread = container.querySelector(".waMessages")?.textContent || "";
    expect(thread).toContain("Mensagem do Rafael");
    expect(thread).not.toContain("Mensagem da Mariana");
  });

  it("mostra o funil da IA, o que trava a venda e a leitura da conversa", async () => {
    api.getWhatsAppInsights.mockResolvedValue({ ...INSIGHTS,
      stages: [{ key: "interessada", label: "Interessada", count: 5, share: 50 }, { key: "negociando", label: "Negociando", count: 3, share: 30 }, { key: "comprou", label: "Comprou", count: 2, share: 20 }],
      interpreted_conversations: 10,
      objections: [{ key: "frete", label: "Frete", count: 4 }, { key: "preco", label: "Preço", count: 2 }],
      ads: [{ ...INSIGHTS.ads[0], advanced: 3, top_objection: { key: "frete", label: "Frete", count: 2 } }] });
    api.getWhatsAppInbox.mockResolvedValue({ ...INBOX, conversations: [{ ...INBOX.conversations[0],
      insight: { stage: "negociando", interests: ["Oud", "splits 10 ml"], objections: ["frete"], next_step: "mandar link do cartão em 3x", summary: "Quer Oud em 10 ml.", updated_at: "2026-11-09T20:40:00Z" } }] });
    api.getWhatsAppMessages.mockResolvedValue({ available: true, messages: [] });
    await act(async () => root.render(<WhatsApp />));
    await flush();
    const text = container.textContent || "";
    expect(text).toContain("Onde as conversas estão");
    expect(text).toContain("10 conversas");
    expect(text).toContain("O que trava a venda");
    expect(text).toContain("Frete4");
    expect(text).toContain("trava: frete");
    expect(text).toContain("Leitura da IA");
    expect(text).toContain("Quer Oud em 10 ml.");
    expect(text).toContain("Próximo passo: mandar link do cartão em 3x");
    expect(text).toContain("Interesses: Oud, splits 10 ml");
  });

  it("equipe responde dentro da janela de 24 h e a conversa recarrega; fora da janela não tem caixa de resposta", async () => {
    const open = new Date(Date.now() + 3 * 3600_000).toISOString();
    api.getWhatsAppInsights.mockResolvedValue(INSIGHTS);
    api.getWhatsAppInbox.mockResolvedValue({ ...INBOX, conversations: [{ ...INBOX.conversations[1], service_window_expires_at: open }, INBOX.conversations[0]] });
    api.getWhatsAppMessages.mockResolvedValue({ available: true, messages: [] });
    api.replyWhatsApp.mockResolvedValue({ status: "sent", ai_paused_minutes: 240 });
    await act(async () => root.render(<WhatsApp />));
    await flush();
    const box = container.querySelector("#wa-reply") as HTMLTextAreaElement;
    expect(box).toBeTruthy();
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(box, "Tem sim, 50 ml!");
      box.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => (container.querySelector(".waComposer button") as HTMLButtonElement).click());
    await flush();
    expect(api.replyWhatsApp).toHaveBeenCalledWith("c2", "Tem sim, 50 ml!");
    expect(container.textContent).toContain("A IA fica quieta nesta conversa por 4 h");
    expect(api.getWhatsAppMessages.mock.calls.length).toBeGreaterThanOrEqual(2);
    const other = [...container.querySelectorAll(".waConvList button")].find((b) => b.textContent?.includes("Mariana")) as HTMLButtonElement;
    await act(async () => other.click());
    await flush();
    expect(container.querySelector("#wa-reply")).toBeNull();
    expect(container.textContent).toContain("Passou de 24 h");
  });
});
