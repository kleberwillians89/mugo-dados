import { describe, expect, it } from "vitest";
import { storageUploadError } from "./library";

describe("motivo da recusa do Storage", () => {
  it("diz o motivo em vez de só pedir para tentar de novo", () => {
    expect(storageUploadError(400, JSON.stringify({ statusCode: "415", error: "invalid_mime_type", message: "mime type application/pdf is not supported" })))
      .toContain("tipo de arquivo");
    expect(storageUploadError(413, JSON.stringify({ error: "Payload too large", message: "The object exceeded the maximum allowed size" }))).toContain("limite");
    expect(storageUploadError(400, JSON.stringify({ error: "InvalidJWT", message: "\"exp\" claim timestamp check failed (expired)" }))).toContain("expirou");
    expect(storageUploadError(500, "oops")).toContain("erro 500");
  });
});
