import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ArtViewer from "./ArtViewer";
import type { StudioAsset } from "../../app/studioAssets";

const asset = (id: string, kind: StudioAsset["kind"], url: string | null = `https://sb/${id}`): StudioAsset =>
  ({ id, kind, mime_type: kind === "video" ? "video/mp4" : "image/png", url, thumb_url: `https://sb/${id}.thumb`, width: 1080, height: 1350, duration_seconds: null });

describe("ArtViewer", () => {
  it("mostra o carrossel na ordem, com contador e navegação", () => {
    const html = renderToStaticMarkup(<ArtViewer assets={[asset("a", "imagem"), asset("b", "imagem"), asset("c", "imagem")]} label="Arte" />);
    expect([...html.matchAll(/<img src="([^"]+)"/g)].map((m) => m[1])).toEqual(["https://sb/a", "https://sb/b", "https://sb/c"]);
    expect(html).toContain("1/3");
    expect(html).toContain('aria-label="Próximo slide"');
    expect(html).not.toContain('aria-label="Slide anterior"');
  });

  it("toca vídeo de Reels com a miniatura como capa e ignora PDF e link ausente", () => {
    const html = renderToStaticMarkup(<ArtViewer assets={[asset("v", "video"), asset("p", "pdf"), asset("x", "imagem", null)]} />);
    expect(html).toContain('<video src="https://sb/v" poster="https://sb/v.thumb"');
    expect(html).not.toContain("<img");
    expect(html).not.toContain("artCount");
  });

  it("não desenha nada sem arte", () => {
    expect(renderToStaticMarkup(<ArtViewer assets={[]} />)).toBe("");
  });
});
