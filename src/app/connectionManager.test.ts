import { describe, expect, it } from "vitest";
import { resolveOperationalMetaConnectionId, selectUniqueConnection } from "./connectionManager";

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
