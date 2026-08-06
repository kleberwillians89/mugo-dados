import { describe, expect, it } from "vitest";
import {
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
