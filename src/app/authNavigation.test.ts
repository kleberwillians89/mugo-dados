import { describe, expect, it } from "vitest";
import {
  canManageIntegrationsRole,
  routeAfterInvitationAccepted,
  shouldOpenHomeAfterSignIn,
} from "./authNavigation";

describe("auth navigation", () => {
  const decision = (overrides: Partial<Parameters<typeof shouldOpenHomeAfterSignIn>[0]> = {}) => shouldOpenHomeAfterSignIn({
    event: "SIGNED_IN", bootstrapCompleted: true, knownUserId: null, nextUserId: "user-1", requestedRoute: "home", hasSetupSignal: false, ...overrides,
  });

  it("abre Início em login explícito feito pela entrada normal", () => {
    expect(decision()).toBe(true);
  });

  it.each(["/google", "/ecommerce", "/inteligencia"])("preserva %s durante restauração da sessão", () => {
    expect(decision({ knownUserId: "user-1" })).toBe(false);
  });

  it.each(["central", "calendar", "google"])("preserva a rota interna direta %s após login", (requestedRoute) => {
    expect(decision({ requestedRoute })).toBe(false);
  });

  it("preserva retornos OAuth e onboarding na entrada", () => {
    expect(decision({ hasSetupSignal: true })).toBe(false);
  });

  it("não redireciona antes de o bootstrap identificar a sessão restaurada", () => {
    expect(decision({ bootstrapCompleted: false })).toBe(false);
  });

  it("ignora INITIAL_SESSION e TOKEN_REFRESHED", () => {
    expect(decision({ event: "INITIAL_SESSION" })).toBe(false);
    expect(decision({ event: "TOKEN_REFRESHED", knownUserId: "user-1" })).toBe(false);
  });
});

describe("routeAfterInvitationAccepted — onboarding converge para Integrações", () => {
  it.each(["platform_admin", "agency_admin", "client_admin", "owner", "admin", "CLIENT_ADMIN"])(
    "papel %s que gerencia integrações vai para integrations",
    (role) => {
      expect(routeAfterInvitationAccepted(role)).toBe("integrations");
      expect(canManageIntegrationsRole(role)).toBe(true);
    }
  );

  it.each(["viewer", "", null, undefined, "desconhecido"])(
    "papel %s sem mutação segue para o dashboard (meta)",
    (role) => {
      expect(routeAfterInvitationAccepted(role as string)).toBe("meta");
      expect(canManageIntegrationsRole(role as string)).toBe(false);
    }
  );
});
