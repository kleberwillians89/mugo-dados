import { describe, expect, it } from "vitest";
import { storageError } from "./artUpload";

const video = new File([new Uint8Array(10)], "reels.mp4", { type: "video/mp4" });
const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("storageError", () => {
  it("explica tipo não liberado no bucket", async () => {
    expect(await storageError(res(400, { statusCode: "415", error: "invalid_mime_type", message: "mime type video/mp4 is not supported" }), video, true))
      .toContain("ainda não aceita vídeo");
  });
  it("explica limite de tamanho", async () => {
    expect(await storageError(res(413, { message: "The object exceeded the maximum allowed size" }), video, true)).toContain("passou do limite");
  });
  it("mostra o motivo cru quando não reconhece", async () => {
    expect(await storageError(res(403, { message: "new row violates row-level security policy" }), video, true)).toContain("403: new row violates");
  });
});
