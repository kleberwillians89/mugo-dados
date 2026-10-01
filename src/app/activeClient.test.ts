// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import {
  clearTenantBrowserState,
  canonicalizeClientId,
  getActiveClient,
  getActiveClientId,
  setActiveClient,
} from "./activeClient";

// Node 26 expõe Web Storage experimental sem arquivo configurado e pode
// sombrear o storage do jsdom. Mantém este teste independente do runtime.
if (!window.localStorage) {
  const values = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    value: {
      clear: () => values.clear(),
      getItem: (key: string) => values.get(key) ?? null,
      removeItem: (key: string) => values.delete(key),
      setItem: (key: string, value: string) => values.set(key, value),
      key: (index: number) => [...values.keys()][index] ?? null,
      get length() { return values.size; },
    },
  });
}

describe("estado multiempresa no navegador", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("normaliza o tenant legado da Amalie para o identificador operacional", () => {
    expect(canonicalizeClientId("9cd90217-ccba-4467-a095-eedc21fe6e86")).toBe("amalie");
    setActiveClient({ id: "9cd90217-ccba-4467-a095-eedc21fe6e86", name: "Amalie" });
    expect(getActiveClientId()).toBe("amalie");
  });

  it("troca a empresa ativa sem manter a empresa anterior", () => {
    setActiveClient({ id: "amalie", name: "Amalie", role: "client_admin" });
    expect(getActiveClientId()).toBe("amalie");
    setActiveClient({ id: "roove", name: "Roove", role: "agency_admin" });
    expect(getActiveClient()).toEqual({ id: "roove", name: "Roove", role: "agency_admin" });
  });

  it("logout remove empresa, conexão e caches tenant", () => {
    setActiveClient({ id: "amalie", name: "Amalie" });
    window.localStorage.setItem("mugo_dados.active_connection_id", "connection-1");
    window.sessionStorage.setItem("client-dashboard-cache:amalie", "{}");
    window.sessionStorage.setItem("unrelated", "preserve");

    clearTenantBrowserState();

    expect(getActiveClient()).toBeNull();
    expect(window.localStorage.getItem("mugo_dados.active_connection_id")).toBeNull();
    expect(window.sessionStorage.getItem("client-dashboard-cache:amalie")).toBeNull();
    expect(window.sessionStorage.getItem("unrelated")).toBe("preserve");
  });
});
