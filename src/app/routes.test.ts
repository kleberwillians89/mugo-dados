import { describe, expect, it } from "vitest";
import { approvalTokenFromPath, getAppRouteFromPath, getPathForRoute, getPublicAppRouteFromPath } from "./routes";
import { canViewAppRoute } from "./teamRules";

describe("platform routes", () => {
  it("distinguishes goals from the existing Meta route", () => {
    expect(getAppRouteFromPath("/metas")).toBe("goals");
    expect(getAppRouteFromPath("/meta")).toBe("meta");
    expect(getPathForRoute("goals")).toBe("/metas");
  });
  it("Social Media mora em /social-media e o endereço antigo da Redação continua abrindo", () => {
    expect(getPathForRoute("campaigns")).toBe("/social-media");
    expect(getAppRouteFromPath("/social-media")).toBe("campaigns");
    expect(getAppRouteFromPath("/redacao")).toBe("campaigns");
  });
  it("preserva acesso ao ambiente unificado para quem tem apenas Calendário, sem conceder Social Media", () => {
    const calendarOnly = (code: string) => code === "calendar.view";
    expect(canViewAppRoute("campaigns", calendarOnly)).toBe(true);
    expect(canViewAppRoute("calendar", calendarOnly)).toBe(true);
    expect(calendarOnly("social_media.view")).toBe(false);
    const socialOnly = (code: string) => code === "social_media.view";
    expect(canViewAppRoute("campaigns", socialOnly)).toBe(true);
    expect(canViewAppRoute("calendar", socialOnly)).toBe(false);
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
    expect(getAppRouteFromPath("/origem-das-vendas")).toBe("origins");
    expect(getPathForRoute("origins")).toBe("/origem-das-vendas");
    expect(getPathForRoute("ecommerce")).toBe("/ecommerce");
  });

  it("maps the Studio routes", () => {
    expect(getAppRouteFromPath("/biblioteca")).toBe("not_found");
    expect(getAppRouteFromPath("/calendario")).toBe("calendar");
    expect(getAppRouteFromPath("/aprovacao")).toBe("calendar"); // aprovação mora no Calendário (Fluxo)
    expect(getPathForRoute("approval")).toBe("/calendario");
    expect(getAppRouteFromPath("/midia")).toBe("media");
    expect(getPathForRoute("media")).toBe("/midia");
  });

  it("maps the automations center both ways", () => {
    expect(getAppRouteFromPath("/automacoes")).toBe("automations");
    expect(getPathForRoute("automations")).toBe("/automacoes");
  });

  it("maps the creators module both ways", () => {
    expect(getAppRouteFromPath("/criadores")).toBe("creators");
    expect(getPathForRoute("creators")).toBe("/criadores");
  });

  it("reads the approval token, even with the literal {{1}} left by the Meta template button", () => {
    const token = "Cl18j4HG89zp1u1bQXkePI32xpYFMydAoeSUu1ZsBuU";
    expect(approvalTokenFromPath(`/aprovar/${token}`)).toBe(token);
    expect(approvalTokenFromPath(`/aprovar/%7B%7B1%7D%7D${token}`)).toBe(token);
    expect(approvalTokenFromPath("/aprovar/curto")).toBeNull();
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
