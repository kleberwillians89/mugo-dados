// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getMentions, reviewMention } = vi.hoisted(() => ({ getMentions: vi.fn(), reviewMention: vi.fn() }));
vi.mock("../../app/brandHealth", async (orig) => ({ ...(await orig<typeof import("../../app/brandHealth")>()), getMentions, reviewMention }));

import MentionReview from "./MentionReview";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const comment = {
  id: "7", source: "comments", network: "instagram", at: "2026-11-03T10:00:00Z", author: "@ana", text: "Que bomba esse perfume",
  sentiment: "negativo", sentiment_ai: "negativo", theme: "perfume", excluded: false, reviewed_at: null,
  post: { permalink: "https://instagram.com/p/x", caption: "Lançamento", at: "2026-11-02T10:00:00Z", thumb: null },
};

async function mount(onChanged?: () => void) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => { createRoot(host).render(<MentionReview start="2026-11-01" end="2026-11-30" onChanged={onChanged} />); });
  await flush();
  const info = host.querySelector<HTMLButtonElement>('button[aria-label="De onde veio e revisar"]');
  await act(async () => { info?.click(); });
  return host;
}

describe("MentionReview", () => {
  beforeEach(() => { getMentions.mockReset(); reviewMention.mockReset(); document.body.innerHTML = ""; });

  it("mostra de onde veio e deixa a equipe corrigir e tirar da avaliação", async () => {
    getMentions.mockResolvedValue({ items: [comment], has_more: false, review_enabled: true, can_review: true });
    reviewMention.mockResolvedValue({ id: "7", source: "comments", sentiment: "positivo", sentiment_ai: "negativo", excluded: false, reviewed_at: "2026-11-12T10:00:00Z" });
    const changed = vi.fn();
    const host = await mount(changed);
    expect(host.querySelector("a")?.getAttribute("href")).toBe("https://instagram.com/p/x");
    expect(host.textContent).toContain("Lançamento");
    expect(host.textContent).toContain("A IA entendeu");
    const select = host.querySelector<HTMLSelectElement>(".bhMentionEdit select")!;
    await act(async () => {
      select.value = "positivo";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flush();
    expect(reviewMention).toHaveBeenCalledWith("comments", "7", { sentiment: "positivo" });
    expect(changed).toHaveBeenCalled();
    expect(host.textContent).toContain("revisado pela equipe");
    reviewMention.mockResolvedValue({ id: "7", source: "comments", sentiment: "positivo", sentiment_ai: "negativo", excluded: true, reviewed_at: "2026-11-12T10:01:00Z" });
    await act(async () => { host.querySelector<HTMLInputElement>('.bhMentionEdit input[type="checkbox"]')!.click(); });
    await flush();
    expect(reviewMention).toHaveBeenLastCalledWith("comments", "7", { excluded: true });
    expect(host.textContent).toContain("fora da avaliação");
  });

  it("quem não pode revisar só vê a origem", async () => {
    getMentions.mockResolvedValue({ items: [comment], has_more: false, review_enabled: true, can_review: false });
    const host = await mount();
    expect(host.textContent).toContain("Só a equipe pode corrigir a avaliação.");
    expect(host.querySelector(".bhMentionEdit")).toBeNull();
  });
});
