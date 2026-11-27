import { describe, expect, it } from "vitest";
import { campaignCategory } from "./MediaClientCampaigns";

describe("classificação de campanhas no Mídia On", () => {
  it("distingue ativas, pausadas, arquivadas, análise e problemas", () => {
    expect(campaignCategory({ status: "ACTIVE" })).toBe("active");
    expect(campaignCategory({ status: "PAUSED" })).toBe("paused");
    expect(campaignCategory({ status: "CAMPAIGN_PAUSED" })).toBe("paused");
    expect(campaignCategory({ status: "ARCHIVED" })).toBe("finished");
    expect(campaignCategory({ status: "PENDING_REVIEW" })).toBe("review");
    expect(campaignCategory({ status: "WITH_ISSUES" })).toBe("issues");
  });

  it("campanha cuja data final passou é encerrada mesmo se Meta retornar ativa", () => {
    const now = Date.parse("2026-11-20T13:00:00Z");
    expect(campaignCategory({ status: "ACTIVE", stop_time: "2026-11-19T23:59:00Z" }, now)).toBe("finished");
    expect(campaignCategory({ status: "ACTIVE", stop_time: "2026-11-25T23:59:00Z" }, now)).toBe("active");
  });
});
