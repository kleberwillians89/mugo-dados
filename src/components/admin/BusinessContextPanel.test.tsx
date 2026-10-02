// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({ getBusinessContext: vi.fn(), saveBusinessContext: vi.fn() }));

vi.mock("../../app/api", () => api);
vi.mock("../../app/activeClient", () => ({
  getActiveClientId: () => "curavino",
  getActiveClientName: () => "Curavino",
}));

import BusinessContextPanel from "./BusinessContextPanel";

const EMPTY_CONTEXT = {
  segment: null, product_description: null, audience: null, positioning: null,
  differentiators: null, commercial_context: null, goals: null, strategic_notes: null,
};

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getBusinessContext.mockResolvedValue({
    ok: true, client_id: "curavino", available: true,
    context: { ...EMPTY_CONTEXT, segment: "Vinhos", audience: "Consumidor final" },
  });
  api.saveBusinessContext.mockImplementation(async (payload: Record<string, string | null>) => ({
    ok: true, client_id: "curavino", available: true,
    context: { ...EMPTY_CONTEXT, ...payload },
  }));
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function render(canEdit = true) {
  await act(async () => root.render(<BusinessContextPanel canEdit={canEdit} />));
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
}

function field(label: string) {
  const labels = [...container.querySelectorAll("label")];
  const match = labels.find((item) => item.textContent?.startsWith(label));
  return match?.querySelector("textarea") as HTMLTextAreaElement | undefined;
}

function button(text: string) {
  return [...container.querySelectorAll("button")].find((item) => item.textContent === text) as HTMLButtonElement | undefined;
}

// React escuta o setter nativo: atribuir .value direto não dispara onChange.
const nativeValue = Object.getOwnPropertyDescriptor(
  window.HTMLTextAreaElement.prototype,
  "value"
)?.set;

async function type(label: string, value: string) {
  const input = field(label);
  if (!input) throw new Error(`Campo não encontrado: ${label}`);
  await act(async () => {
    nativeValue?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("Contexto estratégico — administração do contexto da empresa", () => {
  it("carrega o contexto salvo da empresa ativa, sem enviar client_id", async () => {
    await render();
    expect(api.getBusinessContext).toHaveBeenCalledTimes(1);
    // Tenant vem do contexto autorizado: a chamada não carrega empresa alguma.
    const [firstArg] = api.getBusinessContext.mock.calls[0];
    expect(JSON.stringify(firstArg ?? {})).not.toContain("curavino");
    expect(field("Segmento")?.value).toBe("Vinhos");
    expect(field("Público")?.value).toBe("Consumidor final");
    expect(container.textContent).toContain("Curavino");
  });

  it("explica para que serve, em linguagem de negócio", async () => {
    await render();
    expect(container.textContent).toContain("ajudam a Inteligência a interpretar os dados dentro da realidade");
  });

  it("não salva a cada tecla e avisa alterações pendentes", async () => {
    await render();
    expect(container.querySelector('[data-testid="business-context-dirty"]')).toBeNull();
    await type("Segmento", "Vinhos naturais");
    expect(api.saveBusinessContext).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="business-context-dirty"]')?.textContent)
      .toContain("alterações não salvas");
  });

  it("salva só no botão e confirma o resultado", async () => {
    await render();
    await type("Objetivos", "Dobrar a recompra");
    await act(async () => button("Salvar contexto")?.click());
    await act(async () => Promise.resolve());
    expect(api.saveBusinessContext).toHaveBeenCalledTimes(1);
    expect(api.saveBusinessContext.mock.calls[0][0].goals).toBe("Dobrar a recompra");
    expect(container.textContent).toContain("Contexto salvo");
    expect(container.querySelector('[data-testid="business-context-dirty"]')).toBeNull();
  });

  it("campo apagado vira nulo, não string vazia", async () => {
    await render();
    await type("Segmento", "   ");
    await act(async () => button("Salvar contexto")?.click());
    await act(async () => Promise.resolve());
    expect(api.saveBusinessContext.mock.calls[0][0].segment).toBeNull();
  });

  it("respeita o limite de 1200 caracteres do backend", async () => {
    await render();
    await type("Observações estratégicas", "x".repeat(5000));
    expect(field("Observações estratégicas")?.value.length).toBe(1200);
    expect(field("Observações estratégicas")?.getAttribute("maxlength")).toBe("1200");
  });

  it("erro ao carregar é informado sem derrubar o painel", async () => {
    api.getBusinessContext.mockRejectedValue(new Error("Falha na leitura"));
    await render();
    expect(container.querySelector(".companiesError")?.textContent).toContain("Falha na leitura");
    expect(container.querySelector('[data-testid="business-context-panel"]')).not.toBeNull();
  });

  it("erro ao salvar mantém o que foi digitado", async () => {
    api.saveBusinessContext.mockRejectedValue(new Error("Sem permissão"));
    await render();
    await type("Segmento", "Vinhos naturais");
    await act(async () => button("Salvar contexto")?.click());
    await act(async () => Promise.resolve());
    expect(container.querySelector(".companiesError")?.textContent).toContain("Sem permissão");
    expect(field("Segmento")?.value).toBe("Vinhos naturais");
  });

  it("viewer lê mas não edita", async () => {
    await render(false);
    expect(button("Salvar contexto")).toBeUndefined();
    expect(field("Segmento")?.disabled).toBe(true);
    expect(container.textContent).toContain("A edição é de administradores da empresa");
    expect(api.saveBusinessContext).not.toHaveBeenCalled();
  });

  it("perfil de gestão edita e usa os mesmos campos do backend", async () => {
    await render(true);
    expect(button("Salvar contexto")).toBeTruthy();
    expect(field("Segmento")?.disabled).toBe(false);
    await type("Segmento", "Vinhos naturais");
    await act(async () => button("Salvar contexto")?.click());
    await act(async () => Promise.resolve());
    expect(Object.keys(api.saveBusinessContext.mock.calls[0][0]).sort()).toEqual([
      "audience", "commercial_context", "differentiators", "goals",
      "positioning", "product_description", "segment", "strategic_notes",
    ]);
  });

  it("sem alteração real, o salvar fica inerte", async () => {
    await render();
    await type("Segmento", "Vinhos");
    expect(button("Salvar contexto")?.disabled).toBe(true);
    await act(async () => button("Salvar contexto")?.click());
    expect(api.saveBusinessContext).not.toHaveBeenCalled();
  });

  it("mostra carregamento antes do contexto chegar", async () => {
    let release: (value: unknown) => void = () => {};
    api.getBusinessContext.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    await act(async () => root.render(<BusinessContextPanel canEdit />));
    expect(container.textContent).toContain("Carregando contexto da empresa");
    await act(async () => {
      release({ ok: true, client_id: "curavino", available: false, context: EMPTY_CONTEXT });
    });
  });
});
