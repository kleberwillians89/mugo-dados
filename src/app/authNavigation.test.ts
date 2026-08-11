import { describe, expect, it } from "vitest";
import { shouldOpenMetaAfterSignIn } from "./authNavigation";

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
