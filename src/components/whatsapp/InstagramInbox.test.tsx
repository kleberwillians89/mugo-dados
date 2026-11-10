// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const now = new Date().toISOString();
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "ruah" }));
vi.mock("../../app/whatsapp", () => ({
  getInstagramInbox: vi.fn(async () => ({
    threads: [{ sender_id: "555", username: "ana", follows: true, last_at: now, last_text: "tem frete?", last_direction: "in",
      last_by_app: false, waiting: true, review: true, window_open: true, messages: 2 }],
    counts: { conversations: 1, waiting: 1, review: 1 },
  })),
  getInstagramThread: vi.fn(async () => ({ sender_id: "555", username: "ana", follows: true, window_open: true, messages: [
    { id: "1", direction: "out", text: "Oi @ana!", by_app: true, status: "respondido", reply_kind: "oi", at: now, note: null },
    { id: "2", direction: "in", text: "tem frete?", by_app: false, status: "revisao", reply_kind: "ia", at: now, note: "frete fora do negócio" },
  ] })),
  replyInstagram: vi.fn(async () => ({ status: "enviado", at: now })),
}));

import InstagramInbox from "./InstagramInbox";
import { replyInstagram } from "../../app/whatsapp";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("Direct do Instagram na tela do WhatsApp", () => {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  afterEach(() => vi.clearAllMocks());

  it("lista, abre a conversa e responde pela equipe", async () => {
    await act(async () => root.render(<InstagramInbox />));
    expect(container.textContent).toContain("@ana");
    expect(container.textContent).toContain("IA pediu a equipe");
    await act(async () => (container.querySelector(".waConvList button") as HTMLButtonElement).click());
    expect(container.textContent).toContain("oi automático");
    expect(container.textContent).toContain("frete fora do negócio");
    const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(textarea, "Frete grátis acima de R$ 300!");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => (container.querySelector(".waComposer button") as HTMLButtonElement).click());
    expect(replyInstagram).toHaveBeenCalledWith("555", "Frete grátis acima de R$ 300!");
  });
});
