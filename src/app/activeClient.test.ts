// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import {
  clearTenantBrowserState,
  getActiveClient,
  getActiveClientId,
  setActiveClient,
} from "./activeClient";

describe("estado multiempresa no navegador", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
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
