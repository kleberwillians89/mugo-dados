// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const studio = vi.hoisted(() => ({
  listItemReferences: vi.fn(), listItemComments: vi.fn(), addItemReference: vi.fn(), addItemComment: vi.fn(), deleteReference: vi.fn(), uploadReference: vi.fn(),
}));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));

import PostReview from "./PostReview";

const item = { id: "p1", title: "Reels Black Friday", format: "reels", scheduled_at: "2026-11-27T22:00:00Z", status: "em_revisao",
  caption_draft: "Oferta da semana", art_url: null, hook: null, review_note: "Trocar a cor do título" } as never;
const ref = (id: string, url: string, kind = "link") => ({ id, url, kind, note: null, author_side: "cliente", created_at: "2026-11-11T12:00:00Z", can_delete: true });

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  studio.listItemReferences.mockResolvedValue({ references: [ref("r1", "https://br.pinterest.com/pin/123")] });
  studio.listItemComments.mockResolvedValue({ comments: [{ id: "c1", author_side: "mugo", author_name: null, body: "Subimos a nova versão", created_at: "2026-11-10T12:00:00Z" }] });
  studio.addItemReference.mockImplementation(async (_id: string, input: { url: string; kind?: string }) => ({ ok: true, reference: ref("r2", input.url, input.kind) }));
  studio.addItemComment.mockImplementation(async (_id: string, body: string) => ({ ok: true, comment: { id: "c2", author_side: "cliente", author_name: null, body, created_at: "2026-11-11T12:00:00Z" } }));
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

const type = async (el: HTMLInputElement | HTMLTextAreaElement, value: string) => act(async () => {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value")!.set!;
  setter.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true }));
});
const button = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement;

describe("PostReview", () => {
  it("mostra o último pedido, as referências e a conversa; adiciona link e envia só o comentário", async () => {
    const onDecide = vi.fn(async () => undefined);
    await act(async () => { root.render(<PostReview item={item} handle="@ruah" busy={false} error={null} onClose={() => undefined} onDecide={onDecide} />); });
    expect(host.textContent).toContain("Trocar a cor do título");
    expect(host.textContent).toContain("pinterest.com");
    expect(host.textContent).toContain("Conversa sobre este post (1)");

    await type(host.querySelector(".postReviewRefForm input") as HTMLInputElement, "https://www.instagram.com/p/abc");
    await act(async () => { button("Adicionar").click(); });
    expect(studio.addItemReference).toHaveBeenCalledWith("p1", { url: "https://www.instagram.com/p/abc" });
    expect(host.textContent).toContain("instagram.com");

    await type(host.querySelector(".postReviewNote textarea") as HTMLTextAreaElement, "Gostei, mas e o preço?");
    await act(async () => { button("Só enviar o comentário").click(); });
    expect(studio.addItemComment).toHaveBeenCalledWith("p1", "Gostei, mas e o preço?");
    expect(onDecide).not.toHaveBeenCalled();
    expect(host.textContent).toContain("Conversa sobre este post (2)");
  });

  it("pedir ajuste só com referências manda um aviso para a equipe olhar os anexos", async () => {
    const onDecide = vi.fn(async () => undefined);
    await act(async () => { root.render(<PostReview item={item} handle="@ruah" busy={false} error={null} onClose={() => undefined} onDecide={onDecide} />); });
    await act(async () => { button("Pedir ajuste").click(); });
    expect(onDecide).toHaveBeenCalledWith("rejeitado", "Veja as referências anexadas.");
  });
});
