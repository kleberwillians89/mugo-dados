import { describe, expect, it } from "vitest";
import {
  isEcommerceSyncPending,
  resolveActiveEcommerceProvider,
} from "./ecommerceProvider";
import type { ClientIntegrationConnection } from "./types";

function entry(provider: string, overrides: Partial<ClientIntegrationConnection> = {}): ClientIntegrationConnection {
  return {
    provider,
    connection_id: `${provider}-1`,
    status: "connected",
    authorization_status: "valid",
    sync_status: null,
    account: {},
    assets: {},
    last_sync_at: null,
    last_successful_sync_at: null,
    last_error: null,
    updated_at: null,
    ...overrides,
  };
}

describe("resolveActiveEcommerceProvider — fonte de verdade = conexões do tenant", () => {
  it("1. somente Shopify conectado → shopify", () => {
    const result = resolveActiveEcommerceProvider([entry("meta"), entry("shopify")]);
    expect(result.state).toBe("resolved");
    expect(result.provider).toBe("shopify");
  });

  it("2. somente FBITS conectado → fbits", () => {
    const result = resolveActiveEcommerceProvider([entry("ga4"), entry("fbits")]);
    expect(result.state).toBe("resolved");
    expect(result.provider).toBe("fbits");
  });

  it("3. FBITS conectado sem nenhum sync/pedido continua fbits e fica pendente", () => {
    const result = resolveActiveEcommerceProvider([entry("fbits", { last_sync_at: null })]);
    expect(result.provider).toBe("fbits");
    expect(isEcommerceSyncPending(result.connections)).toBe(true);
  });

  it("4. Shopify conectado sem pedidos continua shopify", () => {
    const result = resolveActiveEcommerceProvider([entry("shopify", { last_sync_at: null })]);
    expect(result.provider).toBe("shopify");
  });

  it("5. nenhuma conexão → estado vazio", () => {
    expect(resolveActiveEcommerceProvider([])).toMatchObject({ state: "none", provider: null });
    expect(resolveActiveEcommerceProvider(null)).toMatchObject({ state: "none", provider: null });
    expect(resolveActiveEcommerceProvider([entry("meta"), entry("ga4")])).toMatchObject({ state: "none" });
  });

  it("6. conexão disconnected não é considerada ativa", () => {
    expect(resolveActiveEcommerceProvider([entry("fbits", { status: "disconnected" })]).state).toBe("none");
    const result = resolveActiveEcommerceProvider([
      entry("shopify", { status: "disconnected" }),
      entry("fbits"),
    ]);
    expect(result).toMatchObject({ state: "resolved", provider: "fbits" });
  });

  it("erro de sync/autorização ainda identifica a plataforma (página mostra o erro)", () => {
    expect(resolveActiveEcommerceProvider([entry("fbits", { status: "token_expired" })]).provider).toBe("fbits");
    const syncError = resolveActiveEcommerceProvider([entry("fbits", { last_error: "falhou" })]);
    expect(syncError.provider).toBe("fbits");
    expect(isEcommerceSyncPending(syncError.connections)).toBe(false);
  });

  it("15. Shopify + FBITS ativos → ambiguous, independente da ordem do array", () => {
    const a = resolveActiveEcommerceProvider([entry("shopify"), entry("fbits")]);
    const b = resolveActiveEcommerceProvider([entry("fbits"), entry("shopify")]);
    expect(a).toMatchObject({ state: "ambiguous", provider: null, candidates: ["shopify", "fbits"] });
    expect(b).toMatchObject({ state: "ambiguous", provider: null, candidates: ["shopify", "fbits"] });
  });

  it("15. escolha explícita resolve a ambiguidade; escolha inválida não", () => {
    const both = [entry("fbits"), entry("shopify")];
    expect(resolveActiveEcommerceProvider(both, "fbits")).toMatchObject({ state: "resolved", provider: "fbits" });
    expect(resolveActiveEcommerceProvider(both, "shopify")).toMatchObject({ state: "resolved", provider: "shopify" });
    expect(resolveActiveEcommerceProvider([entry("fbits")], "shopify")).toMatchObject({ provider: "fbits" });
  });
});
