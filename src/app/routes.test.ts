import { describe, expect, it } from "vitest";
import { getAppRouteFromPath, getPathForRoute, getPublicAppRouteFromPath } from "./routes";

describe("platform routes", () => {
  it("distinguishes goals from the existing Meta route", () => {
    expect(getAppRouteFromPath("/metas")).toBe("goals");
    expect(getAppRouteFromPath("/meta")).toBe("meta");
    expect(getPathForRoute("goals")).toBe("/metas");
  });
  it("maps the protected companies URL", () => {
    expect(getAppRouteFromPath("/empresas")).toBe("companies");
    expect(getPathForRoute("companies")).toBe("/empresas");
  });

  it("keeps tenant reports on their existing routes", () => {
    expect(getAppRouteFromPath("/")).toBe("meta");
    expect(getAppRouteFromPath("/dashboard")).toBe("meta");
    expect(getAppRouteFromPath("/overview")).toBe("meta");
    expect(getAppRouteFromPath("/visao-geral")).toBe("meta");
    expect(getAppRouteFromPath("/google")).toBe("google");
    expect(getAppRouteFromPath("/ecommerce")).toBe("ecommerce");
    expect(getAppRouteFromPath("/integracoes")).toBe("integrations");
    expect(getAppRouteFromPath("/inteligencia")).toBe("intelligence");
    expect(getPathForRoute("intelligence")).toBe("/inteligencia");
    expect(getPathForRoute("ecommerce")).toBe("/ecommerce");
  });

  it("distinguishes an unknown URL from the dashboard", () => {
    expect(getAppRouteFromPath("/rota-inexistente")).toBe("not_found");
  });

  it("recognizes the public legal routes before protected routing", () => {
    expect(getPublicAppRouteFromPath("/privacidade")).toBe("privacy");
    expect(getPublicAppRouteFromPath("/privacidade/")).toBe("privacy");
    expect(getPublicAppRouteFromPath("/exclusao-de-dados")).toBe("data_deletion");
    expect(getPublicAppRouteFromPath("/termos-de-uso")).toBe("terms");
    expect(getPublicAppRouteFromPath("/termos")).toBe("terms");
    expect(getPublicAppRouteFromPath("/meta")).toBeNull();
  });
});
