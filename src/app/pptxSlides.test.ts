// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { extractSlides, slidesFromText } from "./pptxSlides";
import { artKind, canvaEmbed, driveId } from "./artLinks";

// .pptx real (gerado com zipfile do Python): o zip montado dentro do jsdom mistura realms de Uint8Array.
const pptx = () => new Uint8Array(readFileSync(join(__dirname, "__fixtures__", "calendario.pptx")));

describe("extractSlides", () => {
  it("lê texto, links clicáveis e notas, na ordem numérica dos slides", () => {
    const slides = extractSlides(pptx());
    expect(slides.map((s) => s.index)).toEqual([1, 2, 10]);
    expect(slides[1].text).toContain("05/11 18h Reels");
    expect(slides[1].text).toContain("Notas: Legenda: O laranja");
    expect(slides[1].links).toEqual(["https://www.canva.com/design/DAF1/abc/view", "https://drive.google.com/file/d/ABCDEFGHIJK/view"]);
  });

  it("arquivo que não é pptx dá mensagem clara", () => {
    expect(() => extractSlides(new Uint8Array([1, 2, 3]))).toThrow(/pptx/);
  });

  it("texto colado vira um bloco por parágrafo", () => {
    const out = slidesFromText("05/11 Reels\nArte: https://canva.com/x\n\n07/11 Carrossel");
    expect(out).toHaveLength(2);
    expect(out[0].links).toEqual(["https://canva.com/x"]);
  });
});

describe("artLinks", () => {
  it("reconhece Canva e Drive e monta a prévia", () => {
    expect(artKind("https://www.canva.com/design/DAF1/abc/view?utm=x")).toBe("canva");
    expect(canvaEmbed("https://www.canva.com/design/DAF1/abc/view?utm=x")).toBe("https://www.canva.com/design/DAF1/abc/view?embed");
    expect(artKind("https://drive.google.com/file/d/ABCDEFGHIJK/view")).toBe("drive");
    expect(driveId("https://drive.google.com/open?id=ABCDEFGHIJK")).toBe("ABCDEFGHIJK");
    expect(artKind("https://exemplo.com/arte.png")).toBe("outro");
  });
});
