// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ getBrandAgent: vi.fn(), askBrandAgent: vi.fn(), clearBrandAgent: vi.fn(), addKnowledgeFacts: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...state }));

import BrandAgent from "./BrandAgent";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  state.getBrandAgent.mockResolvedValue({ messages: [] });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };
const button = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes(text))!;
async function type(value: string) {
  const textarea = host.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("BrandAgent", () => {
  it("pergunta e mostra a resposta com a fonte", async () => {
    state.askBrandAgent.mockResolvedValue({ ok: true, id: "a1", answer: "O plano anual custa R$ 790.", on_topic: true,
      sources: [{ name: "Tabela de preços.xlsx" }], new_facts: [] });
    await show(<BrandAgent canManage company="M2 Perfomance" />);
    await type("Quanto custa o plano anual?");
    await act(async () => { button("Perguntar").click(); });
    expect(state.askBrandAgent).toHaveBeenCalledWith("Quanto custa o plano anual?");
    expect(host.textContent).toContain("O plano anual custa R$ 790.");
    expect(host.textContent).toContain("Fonte: Tabela de preços.xlsx");
    expect(host.querySelector("textarea")!.value).toBe("");
  });

  it("sugere perguntas quando a conversa está vazia", async () => {
    state.askBrandAgent.mockResolvedValue({ ok: true, id: "a1", answer: "Leve e motivador.", on_topic: true, sources: [], new_facts: [] });
    await show(<BrandAgent canManage={false} company="M2 Perfomance" />);
    await act(async () => { button("tom de voz").click(); });
    expect(state.askBrandAgent).toHaveBeenCalledWith("Qual é o tom de voz da marca?");
  });

  it("guarda o fato novo na memória com um clique e avisa a página", async () => {
    const onLearned = vi.fn();
    state.askBrandAgent.mockResolvedValue({ ok: true, id: "a2", answer: "Anotado.", on_topic: true, sources: [],
      new_facts: ["A M2 não faz promoção em dezembro"] });
    state.addKnowledgeFacts.mockResolvedValue({ ok: true });
    await show(<BrandAgent canManage company="M2 Perfomance" onLearned={onLearned} />);
    await type("A M2 não faz promoção em dezembro");
    await act(async () => { button("Perguntar").click(); });
    await act(async () => { button("Guardar na memória").click(); });
    expect(state.addKnowledgeFacts).toHaveBeenCalledWith(["A M2 não faz promoção em dezembro"]);
    expect(onLearned).toHaveBeenCalled();
    expect(host.textContent).toContain("Guardado na memória da marca");
  });

  it("quem só lê não vê o botão de guardar fatos", async () => {
    state.getBrandAgent.mockResolvedValue({ messages: [
      { id: "u1", role: "user", content: "A M2 abre aos domingos" },
      { id: "a1", role: "assistant", content: "Anotado.", meta: { on_topic: true, sources: [], new_facts: ["A M2 abre aos domingos"] } }] });
    await show(<BrandAgent canManage={false} company="M2 Perfomance" />);
    expect(host.textContent).toContain("Anotado.");
    expect(host.textContent).not.toContain("Guardar na memória");
  });

  it("se a IA falhar, devolve a pergunta para a caixa e mostra o erro", async () => {
    state.askBrandAgent.mockRejectedValue(new Error("A IA não respondeu agora. Tente novamente."));
    await show(<BrandAgent canManage company="M2 Perfomance" />);
    await type("Qual é o público?");
    await act(async () => { button("Perguntar").click(); });
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("não respondeu");
    expect(host.querySelector("textarea")!.value).toBe("Qual é o público?");
    expect(host.querySelectorAll(".chatMsg").length).toBe(0);
  });

  it("limpa a conversa só depois de confirmar", async () => {
    state.getBrandAgent.mockResolvedValue({ messages: [{ id: "u1", role: "user", content: "Oi" }] });
    state.clearBrandAgent.mockResolvedValue({ ok: true });
    await show(<BrandAgent canManage company="M2 Perfomance" />);
    await act(async () => { button("Limpar conversa").click(); });
    expect(state.clearBrandAgent).not.toHaveBeenCalled();
    await act(async () => { button("Apagar").click(); });
    expect(state.clearBrandAgent).toHaveBeenCalled();
    expect(host.querySelectorAll(".chatMsg").length).toBe(0);
  });
});
