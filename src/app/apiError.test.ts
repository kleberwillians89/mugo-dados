import { describe, expect, it } from "vitest";
import {
  normalizeApiErrorPayload,
  selectUsableGoogleConnection,
  selectUsableMetaConnection,
  shouldClearTenantStateOnUnauthorized,
  type GenericConnection,
} from "./api";

describe("structured API errors", () => {
  it("reads nested detail message, code and request id without object coercion", async () => {
    const error = normalizeApiErrorPayload({
      detail: {
        message: "A autorização Google precisa ser renovada.",
        code: "GOOGLE_REAUTH_REQUIRED",
        request_id: "req-nested",
      },
    }, "req-header");

    expect(error.message).toBe("A autorização Google precisa ser renovada.");
    expect(error.code).toBe("GOOGLE_REAUTH_REQUIRED");
    expect(error.requestId).toBe("req-nested");
    expect(error.message).not.toContain("[object Object]");
  });
});

describe("connection safety", () => {
  const connection = (id: string, provider: string): GenericConnection => ({
    id, client_id: "amalie", provider, status: "connected",
    disconnected_at: null, token_available: true,
  });

  it("does not choose the first Google connection when selection is ambiguous", () => {
    const connections = [connection("ga4-a", "ga4"), connection("ga4-b", "ga4")];
    expect(selectUsableGoogleConnection(connections, "ga4", "amalie")).toBeNull();
    expect(selectUsableGoogleConnection(connections, "ga4", "amalie", "ga4-b")?.id).toBe("ga4-b");
  });

  it("does not choose the first Meta connection when selection is ambiguous", () => {
    const connections = [connection("meta-a", "meta"), connection("meta-b", "meta")];
    expect(selectUsableMetaConnection(connections, "amalie")).toBeNull();
    expect(selectUsableMetaConnection(connections, "amalie", "meta-b")?.id).toBe("meta-b");
  });

  it("clears the Mugô session only for application authentication failures", () => {
    expect(shouldClearTenantStateOnUnauthorized(401, "AUTHENTICATION_REQUIRED")).toBe(true);
    expect(shouldClearTenantStateOnUnauthorized(401, "META_REAUTH_REQUIRED")).toBe(false);
    expect(shouldClearTenantStateOnUnauthorized(401, "GOOGLE_REAUTH_REQUIRED")).toBe(false);
  });
});
