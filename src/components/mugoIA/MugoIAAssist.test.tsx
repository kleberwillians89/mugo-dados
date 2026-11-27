// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ askMugoIA: vi.fn(), createFromMugoIA: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...api }));
import PageHeader from "../data/PageHeader";
import { MugoIAAssistContext } from "./assist";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); document.body.innerHTML = ""; vi.clearAllMocks(); });
const click = async (label: string) => act(async () => {
  [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.includes(label))!.click();
});

describe("Mugô IA nas telas de criação", () => {
  it("aparece no cabeçalho do Briefing e pergunta com o foco da tela", async () => {
    api.askMugoIA.mockResolvedValue({ ok: true, id: "m1", answer: "Aqui está o briefing.", on_topic: true, sources: ["Pesquisa de mercado na web"],
      new_facts: [], follow_ups: [], coverage: { read: [], gaps: [] },
      acao: { tipo: "briefing", status: "proposta", titulo: "BF", pedido: "Briefing da Black Friday" } });
    await act(async () => root.render(<MugoIAAssistContext.Provider value={{ screen: "briefing", canCreate: true }}>
      <PageHeader title="Briefing" /></MugoIAAssistContext.Provider>));
    expect(host.querySelector('[data-testid="mia-assist"]')).not.toBeNull();
    await click("Pedir à Mugô IA");
    expect(document.body.textContent).toContain("Mugô IA · Briefing");
    await click("Monta o briefing da próxima campanha");
    expect(api.askMugoIA).toHaveBeenCalledWith("Monta o briefing da próxima campanha da marca", "briefing");
    expect(document.body.textContent).toContain("Aqui está o briefing.");
    expect(document.body.textContent).toContain("Criar briefing");  // a proposta vira rascunho daqui mesmo
    expect(document.body.textContent).toContain("Copiar texto");
  });

  it("no WhatsApp a Mugô IA cria o modelo para aprovar na Meta", async () => {
    await act(async () => root.render(<MugoIAAssistContext.Provider value={{ screen: "whatsapp", canCreate: true }}>
      <PageHeader title="WhatsApp" /></MugoIAAssistContext.Provider>));
    await click("Criar mensagem com a Mugô IA");
    expect(document.body.textContent).toContain("Mugô IA · WhatsApp");
    expect(document.body.textContent).toContain("modelo de WhatsApp para aprovar na Meta");
  });

  it("fora das telas de criação (ou sem permissão) não aparece nem cria espaço vazio", async () => {
    await act(async () => root.render(<PageHeader title="Dashboard" />));
    expect(host.querySelector('[data-testid="mia-assist"]')).toBeNull();
    expect(host.querySelector(".ds-pageHeaderAside")).toBeNull();
    await act(async () => root.render(<MugoIAAssistContext.Provider value={{ screen: "central", canCreate: true }}>
      <PageHeader title="Dashboard" /></MugoIAAssistContext.Provider>));
    expect(host.querySelector('[data-testid="mia-assist"]')).toBeNull();
  });
});
