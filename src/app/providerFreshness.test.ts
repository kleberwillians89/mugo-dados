import { describe, expect, it } from "vitest";
import { findProviderSource, paidMediaNotice, providerEverHadData } from "./providerFreshness";

const sources = [
  { provider: "meta", last_success_at: null, data_max_available: "2026-09-30" },
  { provider: "google_ads", last_success_at: null, data_max_available: null },
  { provider: "ga4", last_success_at: "2026-10-02T16:07:00Z", data_max_available: "2026-10-02" },
];

describe("providerEverHadData — decidido pelo dado, não pela telemetria", () => {
  it("dado gravado conta mesmo sem last_success_at registrado", () => {
    // Exatamente o caso do Google Ads: sync sem rastro, porém com linhas.
    expect(providerEverHadData(sources, "meta")).toBe(true);
  });

  it("sem dado e sem telemetria, não finge que já houve leitura", () => {
    expect(providerEverHadData(sources, "google_ads")).toBe(false);
    expect(providerEverHadData([], "meta")).toBe(false);
    expect(providerEverHadData(null, "meta")).toBe(false);
    expect(providerEverHadData(undefined, "meta")).toBe(false);
  });

  it("dado na tela agora basta, mesmo que o read model ainda não tenha chegado", () => {
    expect(providerEverHadData([], "meta", { hasDataNow: true })).toBe(true);
  });

  it("last_success_at do resumo executivo também serve de prova", () => {
    expect(providerEverHadData([], "meta", { lastSuccessAt: "2026-10-01T10:00:00Z" })).toBe(true);
    expect(providerEverHadData([], "meta", { lastSuccessAt: "   " })).toBe(false);
    expect(providerEverHadData([], "meta", { lastSuccessAt: null })).toBe(false);
  });

  it("provider é comparado sem depender de caixa e ignora nome vazio", () => {
    expect(providerEverHadData([{ provider: "META", data_max_available: "2026-09-30" }], "meta")).toBe(true);
    expect(providerEverHadData(sources, "")).toBe(false);
    expect(findProviderSource(sources, "ga4")?.data_max_available).toBe("2026-10-02");
    expect(findProviderSource(sources, "shopify")).toBeNull();
  });

  it("um provider não responde pelo outro", () => {
    expect(providerEverHadData(sources, "ga4")).toBe(true);
    expect(providerEverHadData(sources, "google_ads")).toBe(false);
  });
});

describe("paidMediaNotice — nunca contradiz dado existente", () => {
  it("com dado existente, informa o período sem falar de primeira importação", () => {
    const notice = paidMediaNotice({ provider: "Meta Ads", syncStatus: "never", everHadData: true });
    expect(notice.title).toBe("Sem dados de Meta Ads neste período");
    expect(notice.body).not.toContain("primeira importação");
    expect(notice.title).not.toContain("Aguardando");
  });

  it("só sem nenhum dado é que aparece a espera da primeira importação", () => {
    const notice = paidMediaNotice({ provider: "Meta Ads", syncStatus: "never", everHadData: false });
    expect(notice.title).toBe("Aguardando sincronização válida");
    expect(notice.body).toContain("primeira importação");
  });

  it("job parcial ou sem dados mantém o diagnóstico da plataforma", () => {
    const partial = paidMediaNotice({
      provider: "Meta Ads", syncStatus: "partial", everHadData: true, lastError: "Janela incompleta",
    });
    expect(partial.title).toBe("Importação de Meta Ads parcial");
    expect(partial.body).toBe("Janela incompleta");

    const skipped = paidMediaNotice({ provider: "Meta Ads", syncStatus: "skipped", everHadData: false });
    expect(skipped.title).toBe("Meta Ads sem dados no período");
    expect(skipped.body).toContain("não retornou dados agregados");
  });

  it("serve a outros providers sem herdar a semântica do Meta", () => {
    expect(paidMediaNotice({ provider: "Google Ads", everHadData: true }).title)
      .toBe("Sem dados de Google Ads neste período");
  });
});
