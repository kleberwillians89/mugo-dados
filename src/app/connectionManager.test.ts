import { describe, expect, it } from "vitest";
import { resolveCommerceConnection, resolveOperationalMetaConnectionId, selectUniqueConnection } from "./connectionManager";

describe("resolveOperationalMetaConnectionId — nunca esconde a única conta paga disponível", () => {
  it("usa a conexão paid única quando o ponteiro salvo não corresponde a nenhuma conta (autorização em cache desatualizada)", () => {
    const connections = [
      { id: "conn-1", platform: "meta_ads", connection_type: "paid", status: "active", disconnected_at: null },
    ];
    // "old-authorization-conn" simula um connection_id salvo no localStorage
    // antes de uma reconexão que criou "conn-1" como a nova conta ativa.
    const result = resolveOperationalMetaConnectionId(connections, "paid", null);
    expect(result).toBe("conn-1");
  });

  it("não escolhe sozinho quando existe mais de uma conta paid ativa — exige seleção explícita", () => {
    const connections = [
      { id: "conn-1", platform: "meta_ads", connection_type: "paid", status: "active", disconnected_at: null },
      { id: "conn-2", platform: "meta_ads", connection_type: "paid", status: "active", disconnected_at: null },
    ];
    const result = resolveOperationalMetaConnectionId(connections, "paid", null);
    expect(result).toBeNull();
  });

  it("respeita a conexão explicitamente solicitada quando ela existe", () => {
    const connections = [
      { id: "conn-1", platform: "meta_ads", connection_type: "paid", status: "active", disconnected_at: null },
      { id: "conn-2", platform: "meta_ads", connection_type: "paid", status: "active", disconnected_at: null },
    ];
    const result = resolveOperationalMetaConnectionId(connections, "paid", "conn-2");
    expect(result).toBe("conn-2");
  });

  it("ignora conexões desconectadas ao aplicar o fallback de conta única", () => {
    const connections = [
      { id: "conn-old", platform: "meta_ads", connection_type: "paid", status: "disconnected", disconnected_at: "2026-01-01" },
      { id: "conn-1", platform: "meta_ads", connection_type: "paid", status: "active", disconnected_at: null },
    ];
    const result = resolveOperationalMetaConnectionId(connections, "paid", null);
    expect(result).toBe("conn-1");
  });

  it("retorna null quando não há nenhuma conexão paid ativa (comportamento original preservado)", () => {
    const connections = [
      { id: "conn-old", platform: "meta_ads", connection_type: "paid", status: "disconnected", disconnected_at: "2026-01-01" },
    ];
    const result = resolveOperationalMetaConnectionId(connections, "paid", null);
    expect(result).toBeNull();
  });
});

describe("resolveCommerceConnection — Ecommerce reconhece Shopify conectado mesmo sem ponteiro local", () => {
  it("usa a única conexão Shopify conectada quando não há seleção salva no localStorage (acabou de conectar via OAuth)", () => {
    const connections = [
      { id: "conn-shopify-1", provider: "shopify", status: "connected", disconnected_at: null },
    ];
    const result = resolveCommerceConnection(connections, null);
    expect(result?.id).toBe("conn-shopify-1");
  });

  it("não escolhe sozinho quando existe Shopify + FBits ativos ao mesmo tempo — exige seleção explícita", () => {
    const connections = [
      { id: "conn-shopify-1", provider: "shopify", status: "connected", disconnected_at: null },
      { id: "conn-fbits-1", provider: "fbits", status: "connected", disconnected_at: null },
    ];
    const result = resolveCommerceConnection(connections, null);
    expect(result).toBeNull();
  });

  it("respeita a conexão explicitamente solicitada quando ela existe", () => {
    const connections = [
      { id: "conn-shopify-1", provider: "shopify", status: "connected", disconnected_at: null },
      { id: "conn-shopify-2", provider: "shopify", status: "connected", disconnected_at: null },
    ];
    const result = resolveCommerceConnection(connections, "conn-shopify-2");
    expect(result?.id).toBe("conn-shopify-2");
  });

  it("solicitação explícita que não corresponde a nenhum candidato continua retornando null (nunca cai para outra conexão)", () => {
    const connections = [
      { id: "conn-shopify-1", provider: "shopify", status: "connected", disconnected_at: null },
    ];
    const result = resolveCommerceConnection(connections, "connection-inexistente");
    expect(result).toBeNull();
  });

  it("sem nenhuma conexão de comércio ativa, continua retornando null (mostra 'Conecte Shopify ou FBits')", () => {
    const connections = [
      { id: "conn-shopify-old", provider: "shopify", status: "disconnected", disconnected_at: "2026-01-01" },
    ];
    const result = resolveCommerceConnection(connections, null);
    expect(result).toBeNull();
  });
});

describe("selectUniqueConnection — comportamento original preservado", () => {
  it("retorna null quando há mais de um match", () => {
    const items = [{ id: "a" }, { id: "b" }];
    expect(selectUniqueConnection(items, () => true)).toBeNull();
  });

  it("retorna o item único quando há exatamente um match", () => {
    const items = [{ id: "a" }, { id: "b" }];
    expect(selectUniqueConnection(items, (item) => item.id === "b")).toEqual({ id: "b" });
  });
});
