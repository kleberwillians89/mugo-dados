import { describe, expect, it } from "vitest";
import { normalizeApiErrorPayload } from "./api";

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
