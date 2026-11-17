// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getContextHealth: vi.fn(), suggestLearning: vi.fn(), confirmLearning: vi.fn() }));
vi.mock("../../app/brandContext", () => api);

import BrandLearning from "./BrandLearning";
import ContextHealth from "./ContextHealth";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
const HEALTH = { ok: true, score: 55, learning: { since: null, last_learning_at: null, new_signals: 6 }, items: [
  { id: "perfil", level: "falta", title: "Perfil da marca incompleto", detail: "Falta: público.", action: { tab: "identidade" } },
  { id: "concorrentes", level: "atencao", title: "Nenhum concorrente cadastrado", detail: "…", action: { route: "benchmark" } },
  { id: "memoria", level: "ok", title: "Memória da marca ativa", detail: "…", action: null },
] };

beforeEach(() => {
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  api.getContextHealth.mockResolvedValue(HEALTH);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };
const button = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes(text));

describe("Saúde do contexto", () => {
  it("mostra o índice, as pendências primeiro e leva para onde resolve", async () => {
    const onAction = vi.fn();
    await show(<ContextHealth onAction={onAction} />);
    expect(host.textContent).toContain("55%");
    expect(host.textContent).toContain("2 ponto(s)");
    expect(host.textContent).toContain("Perfil da marca incompleto");
    expect(host.textContent).not.toContain("Memória da marca ativa");  // ok fica escondido até "Ver tudo"
    await act(async () => { button("Resolver")!.click(); });
    expect(onAction).toHaveBeenCalledWith({ tab: "identidade" });
    await act(async () => { button("Ver tudo")!.click(); });
    expect(host.textContent).toContain("Memória da marca ativa");
  });

  it("se a saúde falhar, a tela segue sem o painel", async () => {
    api.getContextHealth.mockRejectedValue(new Error("x"));
    await show(<ContextHealth />);
    expect(host.querySelector('[data-testid="context-health"]')).toBeNull();
  });
});

describe("Aprender com o uso", () => {
  const SUGGESTION = { ok: true, signals: 6, since: null, message: null, facts: [
    { fato: "A marca não usa emojis nas legendas.", origem: "ajuste", origem_rotulo: "Ajuste pedido pelo cliente", evidencia: "Tirem os emojis", confianca: "alta" },
    { fato: "Os clientes perguntam muito do prazo de entrega.", origem: "whatsapp", origem_rotulo: "Perguntas no WhatsApp", evidencia: "Qual o prazo?", confianca: "media" },
  ] };

  it("mostra os sinais novos, sugere, deixa editar e grava só o marcado", async () => {
    api.suggestLearning.mockResolvedValue(SUGGESTION);
    api.confirmLearning.mockResolvedValue({ ok: true, saved: 1, knowledge: "k", sources: 2 });
    const onLearned = vi.fn();
    await show(<BrandLearning onLearned={onLearned} />);
    expect(button("Buscar aprendizados")!.textContent).toContain("6 sinais novos");
    await act(async () => { button("Buscar aprendizados")!.click(); });
    const boxes = host.querySelectorAll<HTMLInputElement>('.bcFieldHead input[type="checkbox"]');
    expect(boxes[0].checked).toBe(true);   // confiança alta vem marcada
    expect(boxes[1].checked).toBe(false);  // média: só se a pessoa marcar
    expect(host.textContent).toContain("Perguntas no WhatsApp");
    const text = host.querySelector<HTMLTextAreaElement>('[aria-label="Aprendizado 1"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(text, "A marca nunca usa emojis.");
      text.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { button("Guardar 1 na memória")!.click(); });
    expect(api.confirmLearning).toHaveBeenCalledWith(["A marca nunca usa emojis."]);
    expect(host.textContent).toContain("entraram na memória da marca");
    expect(onLearned).toHaveBeenCalled();
  });

  it("sem nada novo, explica e não grava", async () => {
    api.suggestLearning.mockResolvedValue({ ok: true, signals: 1, since: null, facts: [], message: "Ainda não há retorno novo suficiente." });
    await show(<BrandLearning />);
    await act(async () => { button("Buscar aprendizados")!.click(); });
    expect(host.textContent).toContain("Ainda não há retorno novo suficiente.");
    expect(api.confirmLearning).not.toHaveBeenCalled();
  });
});
