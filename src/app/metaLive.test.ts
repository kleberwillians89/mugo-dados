import { describe, expect, it } from "vitest";
import { normalizePermissions } from "./metaLive";

describe("permissões da Meta", () => {
  it("resposta fora do formato vira painel vazio, nunca tela quebrada", () => {
    expect(normalizePermissions(undefined)).toEqual({ features: [], connections: { paid: { connected: false }, organic: { connected: false } } });
    expect(normalizePermissions({ features: [{ key: "comments", state: "missing" }, null] }).features).toHaveLength(1);
  });
});
