// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ getKnowledge: vi.fn(), saveKnowledge: vi.fn(), teachFromFile: vi.fn(), teachFromText: vi.fn(), retryKnowledgeDocument: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...state }));

import BrandKnowledge from "./BrandKnowledge";
import { parseKnowledge } from "./brandKnowledge.helpers";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  state.getKnowledge.mockResolvedValue({ knowledge: "Empresa: M2\n- Treino sábado 6h", sources: 1, updated_at: "2026-11-05T10:00:00Z",
    documents: [{ id: "d1", name: "horarios.pdf", kind: "produto", summary: "Horários de treino", facts_added: 2, truncated: false, created_at: "2026-11-05T10:00:00Z" }] });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };

describe("BrandKnowledge", () => {
  it("mostra o que a IA sabe e os materiais lidos", async () => {
    await show(<BrandKnowledge canManage />);
    expect(host.textContent).toContain("Treino sábado 6h");
    expect(host.textContent).toContain("horarios.pdf");
    expect(host.querySelector('[aria-label="Enviar documentos"]')).not.toBeNull();
  });

  it("quem só lê não vê envio nem edição", async () => {
    await show(<BrandKnowledge canManage={false} />);
    expect(host.querySelector('[aria-label="Enviar documentos"]')).toBeNull();
    expect(host.textContent).not.toContain("Corrigir");
    expect(host.textContent).toContain("Treino sábado 6h");
  });

  it("ensina um texto colado e atualiza o conhecimento", async () => {
    state.teachFromText.mockResolvedValue({ ok: true, knowledge: "Empresa: M2\n- Longão domingo 5h30", sources: 2,
      document: { id: "d2", name: "Texto colado", kind: "institucional", summary: "Longão de domingo", facts_added: 1, truncated: false, created_at: "2026-11-05T11:00:00Z" } });
    await show(<BrandKnowledge canManage />);
    await act(async () => { [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("colar um texto"))!.click(); });
    const textarea = host.querySelector("textarea")!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(textarea, "O longão da M2 acontece todo domingo às 5h30 na orla de Boa Viagem.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const button = [...host.querySelectorAll("button")].find((b) => b.textContent === "Ensinar")!;
    await act(async () => { button.click(); });
    expect(state.teachFromText).toHaveBeenCalledWith(expect.stringContaining("domingo às 5h30"), "institucional");
    expect(host.textContent).toContain("Longão domingo 5h30");
    expect(host.textContent).toContain("2 fontes");
  });

  it("quando a IA falha, avisa que o material ficou guardado e permite tentar de novo", async () => {
    state.teachFromText.mockResolvedValue({ ok: true, knowledge: "Empresa: M2\n- Treino sábado 6h", sources: 1,
      warning: "Material guardado. A IA demorou demais para ler. Use “Tentar de novo” para a IA aprender com ele.",
      document: { id: "d3", name: "Texto colado", kind: "institucional", summary: null, facts_added: 0, truncated: false,
        created_at: "2026-11-06T11:00:00Z", status: "falhou", error: "AI_PROVIDER_TIMEOUT" } });
    state.retryKnowledgeDocument.mockResolvedValue({ ok: true, knowledge: "Empresa: M2\n- Kit de boas-vindas", sources: 2,
      document: { id: "d3", name: "Texto colado", kind: "institucional", summary: "Kit de boas-vindas", facts_added: 1, truncated: false,
        created_at: "2026-11-06T11:00:00Z", status: "aprendido" } });
    await show(<BrandKnowledge canManage />);
    await act(async () => { [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("colar um texto"))!.click(); });
    const textarea = host.querySelector("textarea")!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(textarea, "Todo aluno novo da M2 recebe um kit de boas-vindas com camiseta e squeeze.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { [...host.querySelectorAll("button")].find((b) => b.textContent === "Ensinar")!.click(); });
    expect(host.querySelector(".studioWarn")?.textContent).toContain("Material guardado");
    expect(host.textContent).toContain("guardado, a IA ainda não aprendeu");
    expect(host.querySelector('[role="alert"]')).toBeNull();
    await act(async () => { [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Tentar de novo"))!.click(); });
    expect(state.retryKnowledgeDocument).toHaveBeenCalledWith("d3");
    expect(host.textContent).toContain("Kit de boas-vindas");
    expect(host.textContent).not.toContain("Tentar de novo");
    expect(host.querySelectorAll(".kbDocs li").length).toBe(2);   // não duplica o material reprocessado
  });

  it("divide o conhecimento em blocos por título", () => {
    const parts = parseKnowledge("Empresa:\n- M2 Community Run\n- Recife\n\n## Produtos e preços\n- Plano mensal R$ 89\n**Restrições**\n• Não citar concorrentes");
    expect(parts.map((p) => p.title)).toEqual(["Empresa", "Produtos e preços", "Restrições"]);
    expect(parts[1].items).toEqual(["Plano mensal R$ 89"]);
    expect(parseKnowledge("Texto solto sem título")[0]).toEqual({ title: "Sobre a marca", items: ["Texto solto sem título"] });
  });
});
