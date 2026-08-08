import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import StoriesPanel from "./StoriesPanel";
import type { StoryItem } from "../../app/types";

function story(overrides: Partial<StoryItem>): StoryItem {
  return { id: "story-1", media_type: "IMAGE", ...overrides };
}

function renderWithStory(item: StoryItem): string {
  return renderToStaticMarkup(
    <StoriesPanel stories={[item]} storiesAvailable storiesMessage="" />
  );
}

describe("StoriesPanel — thumb_url (storage persistido) tem prioridade sobre a CDN crua", () => {
  it("usa thumb_url quando disponível, nunca a URL crua da CDN do Instagram", () => {
    const markup = renderWithStory(
      story({
        thumb_url: "https://storage.mugoagencia.com.br/clients/amalie/media/story-1/thumb.jpg",
        thumbnail_url: "https://scontent-xyz.cdninstagram.com/raw-thumb.jpg",
        media_url: "https://scontent-xyz.cdninstagram.com/raw-media.jpg",
      })
    );
    expect(markup).toContain("storage.mugoagencia.com.br");
    expect(markup).not.toContain("cdninstagram.com");
  });

  it("cai para thumbnail_url quando o registro não tem thumb_url persistido (fallback temporário)", () => {
    const markup = renderWithStory(
      story({
        thumbnail_url: "https://example-cdn.test/raw-thumb.jpg",
        media_url: "https://example-cdn.test/raw-media.jpg",
      })
    );
    expect(markup).toContain("example-cdn.test/raw-thumb.jpg");
  });

  it("sem nenhuma URL utilizável, mostra placeholder elegante em vez de imagem quebrada", () => {
    const markup = renderWithStory(story({}));
    expect(markup).toContain("Prévia indisponível");
    expect(markup).not.toContain("<img");
    expect(markup).not.toContain("<video");
  });

  it("URL bloqueada por política da CDN (scontent-/cdninstagram.com) também vira placeholder, mesmo sem thumb_url", () => {
    const markup = renderWithStory(
      story({ thumbnail_url: "https://scontent-gru2-1.cdninstagram.com/raw-thumb.jpg" })
    );
    expect(markup).toContain("Prévia indisponível");
  });
});
