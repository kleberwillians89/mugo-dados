import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import MediaTable from "./MediaTable";

describe("MediaTable mobile preview", () => {
  it("keeps content and a compact Instagram fallback when thumbnail is absent", () => {
    const markup = renderToStaticMarkup(<MediaTable media={[{
      id: "reel-1",
      media_type: "VIDEO",
      media_product_type: "REELS",
      caption: "Coleção de inverno",
      permalink: "https://www.instagram.com/reel/example/",
      timestamp: "2026-08-03T12:00:00Z",
      insights: { reach: 834, total_interactions: 76, comments: 23 },
    }]} />);
    expect(markup).toContain("Prévia indisponível");
    expect(markup).toContain("Coleção de inverno");
    expect(markup).toContain("834");
    expect(markup).toContain("76");
    expect(markup).toContain("23");
    expect(markup).toContain("Ver no Instagram");
  });
});
