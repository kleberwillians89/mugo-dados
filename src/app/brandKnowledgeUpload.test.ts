import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { ORIGINAL_NOTE_PREFIX, needsOcr, originalsFrom } from "./brandKnowledgeUpload";

describe("upload do Conhecimento da marca", () => {
  it("reconhece o pedido de OCR pelo código, não pelo texto", () => {
    expect(needsOcr(new ApiError("qualquer texto", { status: 422, code: "DOC_NEEDS_OCR" }))).toBe(true);
    expect(needsOcr(new ApiError("PDF sem texto", { status: 422, code: "API_ERROR" }))).toBe(false);
    expect(needsOcr(new Error("DOC_NEEDS_OCR"))).toBe(false);
  });

  it("liga cada documento ao original guardado na Biblioteca", () => {
    const items = [
      { id: "1", kind: "arquivo", category: "documento", title: "plano.pdf", url: "https://x/plano.pdf", side: "mugo", note: `${ORIGINAL_NOTE_PREFIX}doc-1` },
      { id: "2", kind: "arquivo", category: "foto", title: "foto.jpg", url: "https://x/foto.jpg", side: "mugo", note: null },
    ] as const;
    expect(originalsFrom([...items])).toEqual({ "doc-1": "https://x/plano.pdf" });
  });
});
