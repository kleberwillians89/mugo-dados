import { describe, expect, it } from "vitest";
import { getAppRouteFromPath, getPathForRoute } from "./routes";

describe("platform routes", () => {
  it("maps the protected companies URL", () => {
    expect(getAppRouteFromPath("/empresas")).toBe("companies");
    expect(getPathForRoute("companies")).toBe("/empresas");
  });

  it("keeps tenant reports on their existing routes", () => {
    expect(getAppRouteFromPath("/")).toBe("dashboard");
    expect(getAppRouteFromPath("/google")).toBe("google");
    expect(getAppRouteFromPath("/integracoes")).toBe("integrations");
    expect(getAppRouteFromPath("/inteligencia")).toBe("intelligence");
    expect(getPathForRoute("intelligence")).toBe("/inteligencia");
  });

  it("distinguishes an unknown URL from the dashboard", () => {
    expect(getAppRouteFromPath("/rota-inexistente")).toBe("not_found");
  });
});
