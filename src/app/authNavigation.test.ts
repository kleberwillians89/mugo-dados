import { describe, expect, it } from "vitest";
import {
  canManageIntegrationsRole,
  routeAfterInvitationAccepted,
  shouldOpenMetaAfterSignIn,
} from "./authNavigation";

describe("auth navigation", () => {
  it("abre Meta em login explícito após bootstrap sem sessão", () => {
    expect(shouldOpenMetaAfterSignIn({ event: "SIGNED_IN", bootstrapCompleted: true, knownUserId: null, nextUserId: "user-1" })).toBe(true);
  });

  it.each(["/google", "/ecommerce", "/inteligencia"])("preserva %s durante restauração da sessão", () => {
    expect(shouldOpenMetaAfterSignIn({ event: "SIGNED_IN", bootstrapCompleted: true, knownUserId: "user-1", nextUserId: "user-1" })).toBe(false);
  });

  it("não redireciona antes de o bootstrap identificar a sessão restaurada", () => {
    expect(shouldOpenMetaAfterSignIn({ event: "SIGNED_IN", bootstrapCompleted: false, knownUserId: null, nextUserId: "user-1" })).toBe(false);
  });

  it("ignora INITIAL_SESSION e TOKEN_REFRESHED", () => {
    expect(shouldOpenMetaAfterSignIn({ event: "INITIAL_SESSION", bootstrapCompleted: true, knownUserId: null, nextUserId: "user-1" })).toBe(false);
    expect(shouldOpenMetaAfterSignIn({ event: "TOKEN_REFRESHED", bootstrapCompleted: true, knownUserId: "user-1", nextUserId: "user-1" })).toBe(false);
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
