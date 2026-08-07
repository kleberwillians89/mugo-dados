import { describe, expect, it } from "vitest";
import {
  classifyGa4Provider,
  getCampaignDisplayName,
  getCampaignIdDetail,
  getGa4ChannelLabel,
  getGa4EventLabel,
  getGa4EventTechnicalDetail,
} from "./ga4Labels";

describe("getGa4EventLabel", () => {
  it("translates known events", () => {
    expect(getGa4EventLabel("page_view")).toBe("Visualizações de página");
    expect(getGa4EventLabel("purchase")).toBe("Compras");
    expect(getGa4EventLabel("add_to_cart")).toBe("Adições ao carrinho");
  });

  it("humanizes unknown events instead of showing the raw identifier", () => {
    expect(getGa4EventLabel("custom_whatsapp_click")).toBe("Custom Whatsapp Click");
  });

  it("falls back to a neutral label when the event name is empty", () => {
    expect(getGa4EventLabel("")).toBe("Evento personalizado");
    expect(getGa4EventLabel(null)).toBe("Evento personalizado");
  });
});

describe("getGa4EventTechnicalDetail", () => {
  it("exposes the raw identifier only for unknown events, as secondary detail", () => {
    expect(getGa4EventTechnicalDetail("custom_whatsapp_click")).toBe("Evento técnico: custom_whatsapp_click");
    expect(getGa4EventTechnicalDetail("page_view")).toBeNull();
  });
});

describe("getGa4ChannelLabel", () => {
  it("translates known channels", () => {
    expect(getGa4ChannelLabel("(direct) / (none)")).toBe("Acesso direto");
    expect(getGa4ChannelLabel("(not set)")).toBe("Não identificado");
    expect(getGa4ChannelLabel("facebook / paid")).toBe("Facebook Ads");
    expect(getGa4ChannelLabel("linktr.ee / referral")).toBe("Linktree");
  });

  it("keeps unknown channels as-is", () => {
    expect(getGa4ChannelLabel("tiktok / paid")).toBe("tiktok / paid");
  });
});

describe("campaign name resolution", () => {
  it("never shows a numeric id as the main title", () => {
    expect(getCampaignDisplayName("120233685343690476")).toBe("Campanha não identificada");
    expect(getCampaignDisplayName("")).toBe("Campanha não identificada");
    expect(getCampaignDisplayName("Black Friday 2026")).toBe("Black Friday 2026");
  });

  it("exposes the id only as secondary detail", () => {
    expect(getCampaignIdDetail("120233685343690476")).toBe("ID da campanha: 120233685343690476");
    expect(getCampaignIdDetail("")).toBeNull();
  });
});

describe("classifyGa4Provider — nunca identificar campanha só pelo campaign_id", () => {
  it("classifica facebook/paid_social como meta_ads, nunca google_ads", () => {
    expect(classifyGa4Provider("facebook", "paid_social")).toBe("meta_ads");
    expect(classifyGa4Provider("instagram", "paid")).toBe("meta_ads");
  });

  it("classifica google/cpc como google_ads", () => {
    expect(classifyGa4Provider("google", "cpc")).toBe("google_ads");
  });

  it("nunca classifica facebook como google_ads mesmo com campaign_id numérico coincidente", () => {
    // O mesmo número de campaign_id pode existir em contas Meta e Google
    // Ads de forma totalmente independente — a classificação nunca pode
    // depender do ID, só de source/medium.
    const provider = classifyGa4Provider("facebook", "paid_social");
    expect(provider).not.toBe("google_ads");
  });

  it("sem evidência suficiente, classifica como unknown", () => {
    expect(classifyGa4Provider(null, null)).toBe("unknown");
    expect(classifyGa4Provider("bing", "cpc")).toBe("unknown");
  });
});

describe("getCampaignDisplayName com contexto de origem", () => {
  it("uma campanha Meta com nome só numérico nunca aparece como 'Campanha não identificada' pura — mostra o provedor real", () => {
    const label = getCampaignDisplayName("123456", { source: "facebook", medium: "paid_social" });
    expect(label).toBe("Meta Ads — campanha 123456");
    expect(label).not.toContain("Google");
  });

  it("uma campanha Google Ads com nome só numérico mostra o provedor real", () => {
    const label = getCampaignDisplayName("123456", { source: "google", medium: "cpc" });
    expect(label).toBe("Google Ads — campanha 123456");
  });

  it("nunca mostra o literal técnico '(not set)' do GA4 como nome de campanha", () => {
    expect(getCampaignDisplayName("(not set)")).toBe("Campanha não identificada");
    expect(getCampaignDisplayName("(not set)", { source: "google", medium: "cpc" })).toBe(
      "Google Ads — campanha não identificada"
    );
  });

  it("sem evidência de origem, mantém o fallback neutro (comportamento anterior preservado)", () => {
    expect(getCampaignDisplayName("123456", { source: null, medium: null })).toBe("Campanha não identificada");
    expect(getCampaignDisplayName("123456")).toBe("Campanha não identificada");
  });

  it("nome de campanha real (não numérico) é sempre priorizado, com ou sem contexto", () => {
    expect(getCampaignDisplayName("Vendas | Agosto", { source: "facebook", medium: "paid_social" })).toBe(
      "Vendas | Agosto"
    );
  });
});
