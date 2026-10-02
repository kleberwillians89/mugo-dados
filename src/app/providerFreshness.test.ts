import { describe, expect, it } from "vitest";
import {
  findProviderSource,
  paidMediaNotice,
  providerEverHadData,
  providerValidUpdatedAt,
} from "./providerFreshness";

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

describe("paidMediaNotice — linguagem de cliente, sem jargão de pipeline", () => {
  const internalWords = /job|pipeline|sincroniza|importa|primeira leitura/i;

  it("com dado existente, informa o período sem falar de sincronização", () => {
    const notice = paidMediaNotice({ provider: "Meta Ads", syncStatus: "never", everHadData: true });
    expect(notice.title).toBe("Ainda não há dados de Meta Ads para este período");
    expect(notice.title).not.toMatch(internalWords);
    expect(notice.body).not.toMatch(internalWords);
  });

  it("sem nenhum dado, o estado vazio é simples e também sem jargão", () => {
    const notice = paidMediaNotice({ provider: "Meta Ads", syncStatus: "never", everHadData: false });
    expect(notice.title).toBe("Ainda não há dados de Meta Ads");
    expect(notice.title).not.toMatch(internalWords);
    expect(notice.body).not.toMatch(internalWords);
  });

  it("resultado parcial não passa por sucesso e não mostra erro técnico", () => {
    const partial = paidMediaNotice({ provider: "Meta Ads", syncStatus: "partial", everHadData: true });
    expect(partial.title).toBe("Dados de Meta Ads incompletos neste período");
    expect(partial.body).toContain("podem mudar na próxima atualização");
    expect(partial.title).not.toMatch(internalWords);
  });

  it("skipped é lido como ausência de dado no período, não como falha", () => {
    const skipped = paidMediaNotice({ provider: "Meta Ads", syncStatus: "skipped", everHadData: false });
    expect(skipped.title).toBe("Ainda não há dados de Meta Ads para este período");
  });

  it("serve a outros providers sem herdar a semântica do Meta", () => {
    expect(paidMediaNotice({ provider: "Google Ads", everHadData: true }).title)
      .toBe("Ainda não há dados de Google Ads para este período");
  });
});

describe("providerValidUpdatedAt — \"atualizado em\" é dado válido, não tentativa", () => {
  it("uma tentativa recente sem sucesso não rejuvenesce a tela", () => {
    const withAttempt = [{
      provider: "meta",
      last_attempt_at: "2026-10-02T18:00:00Z",
      last_success_at: "2026-09-28T10:00:00Z",
      data_max_available: "2026-09-28",
    }];
    expect(providerValidUpdatedAt(withAttempt, "meta")).toBe("2026-09-28T10:00:00Z");
  });

  it("sem sucesso registrado, não inventa data de atualização", () => {
    expect(providerValidUpdatedAt([{ provider: "meta", last_attempt_at: "2026-10-02T18:00:00Z" }], "meta")).toBeNull();
    expect(providerValidUpdatedAt([], "meta")).toBeNull();
    expect(providerValidUpdatedAt(null, "meta")).toBeNull();
  });

  it("aceita o sucesso do resumo executivo como alternativa", () => {
    expect(providerValidUpdatedAt([], "meta", { lastSuccessAt: "2026-10-01T09:00:00Z" }))
      .toBe("2026-10-01T09:00:00Z");
  });

  it("não mistura providers", () => {
    const rows = [
      { provider: "meta", last_success_at: "2026-09-28T10:00:00Z" },
      { provider: "google_ads", last_success_at: "2026-10-02T17:42:00Z" },
    ];
    expect(providerValidUpdatedAt(rows, "google_ads")).toBe("2026-10-02T17:42:00Z");
    expect(providerValidUpdatedAt(rows, "ga4")).toBeNull();
  });
});
