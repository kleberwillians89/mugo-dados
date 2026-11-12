// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CAMPAIGN_FIXTURE, CAMPAIGNS_FIXTURE, CART_FIXTURE, FLOWS_FIXTURE, WA_FIXTURE } from "./email.fixture";

const api = vi.hoisted(() => ({
  getCartRecovery: vi.fn(), saveCartSettings: vi.fn(), registerCartWebhooks: vi.fn(), getWaTemplates: vi.fn(), previewCartEmail: vi.fn(),
  listCampaigns: vi.fn(), getCampaign: vi.fn(), createCampaign: vi.fn(), updateCampaign: vi.fn(), deleteCampaign: vi.fn(),
  previewAudience: vi.fn(), previewEmail: vi.fn(), sendTestEmail: vi.fn(), scheduleCampaign: vi.fn(), cancelCampaign: vi.fn(),
  getFlows: vi.fn(), saveFlow: vi.fn(), previewFlow: vi.fn(),
}));
vi.mock("../../app/emailMarketing", async (orig) => ({ ...(await orig<object>()), ...api }));

const CartRecoveryPanel = (await import("./CartRecoveryPanel")).default;
const CampaignsPanel = (await import("./CampaignsPanel")).default;
const BlockEditor = (await import("./BlockEditor")).default;
const HtmlInput = (await import("./HtmlInput")).default;
const FlowsPanel = (await import("./FlowsPanel")).default;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const button = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === text)!;

describe("E-mail marketing", () => {
  beforeEach(() => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    Object.values(api).forEach((fn) => fn.mockReset());
    api.getCartRecovery.mockResolvedValue(CART_FIXTURE);
    api.getWaTemplates.mockResolvedValue(WA_FIXTURE);
    api.previewCartEmail.mockResolvedValue({ subject: "Ana, seu carrinho", html: "<p>oi</p>" });
    api.previewEmail.mockResolvedValue({ subject: "Ana", html: "<p>oi</p>" });
    api.listCampaigns.mockResolvedValue({ campaigns: CAMPAIGNS_FIXTURE });
  });
  afterEach(() => { act(() => root.unmount()); host.remove(); });

  it("carrinho: mostra receita recuperada, avisa simulação do WhatsApp e explica o Instagram", async () => {
    await act(async () => { root.render(<CartRecoveryPanel canEdit />); });
    await flush();
    expect(host.textContent).toContain("Receita recuperada");
    expect(host.textContent).toContain("9.874,30");
    expect(host.textContent).toContain("18,5%");
    expect(host.textContent).toContain("Modo simulado no WhatsApp");
    expect(host.textContent).toContain("Instagram não entra");
    expect(host.textContent).toContain("Comprou sozinho");
    expect(host.querySelector(".emTemplateBody")?.textContent).toContain("Vimos que você deixou");
  });

  it("carrinho: salvar manda a sequência editada", async () => {
    api.saveCartSettings.mockImplementation(async (s) => ({ settings: s }));
    await act(async () => { root.render(<CartRecoveryPanel canEdit />); });
    await flush();
    const remove = host.querySelectorAll<HTMLButtonElement>('[aria-label="Remover passo"]');
    await act(async () => { remove[2].click(); });
    await act(async () => { button("Salvar").click(); });
    expect(api.saveCartSettings.mock.calls[0][0].steps).toEqual([{ channel: "email", delay_minutes: 60 }, { channel: "whatsapp", delay_minutes: 1440 }]);
    expect(host.textContent).toContain("Recuperação de carrinho salva.");
  });

  it("carrinho: loja que não é Shopify recebe explicação, sem formulário", async () => {
    api.getCartRecovery.mockResolvedValue({ ...CART_FIXTURE, provider: "fbits" });
    await act(async () => { root.render(<CartRecoveryPanel canEdit />); });
    await flush();
    expect(host.textContent).toContain("funciona com lojas Shopify");
    expect(host.querySelector(".emSteps")).toBeNull();
  });

  it("campanhas: lista com taxas e abre o editor com o público", async () => {
    api.getCampaign.mockResolvedValue({ campaign: CAMPAIGN_FIXTURE, stats: null });
    api.previewAudience.mockResolvedValue({ provider: "shopify", count: 1240, base: 9800, with_consent: 6100, blocked: 85, consent_known: true,
      audience: CAMPAIGN_FIXTURE.audience });
    await act(async () => { root.render(<CampaignsPanel canEdit />); });
    await flush();
    expect(host.textContent).toContain("41,2%");
    await act(async () => { button("Reativação 90 dias").click(); });
    await flush();
    expect(host.querySelector<HTMLSelectElement>('[aria-label="Público"]')!.value).toBe("sem_compra");
    await act(async () => { button("Contar público").click(); });
    expect(host.querySelector(".emAudienceCount")?.textContent).toContain("1.240");
  });

  it("campanhas: viewer vê a lista sem botões de criar e apagar", async () => {
    await act(async () => { root.render(<CampaignsPanel canEdit={false} />); });
    await flush();
    expect(host.textContent).not.toContain("Nova campanha");
    expect(host.textContent).not.toContain("Apagar");
  });

  it("editor de blocos adiciona, move e remove", async () => {
    const onChange = vi.fn();
    await act(async () => {
      root.render(<BlockEditor design={{ blocks: [{ type: "titulo", text: "A" }, { type: "texto", text: "B" }] }} onChange={onChange} />);
    });
    await act(async () => { button("+ Botão").click(); });
    expect(onChange.mock.calls[0][0].blocks[2]).toMatchObject({ type: "botao", href: "{{link_loja}}" });
    await act(async () => { host.querySelectorAll<HTMLButtonElement>('[aria-label="Descer"]')[0].click(); });
    expect(onChange.mock.calls[1][0].blocks.map((b: { text?: string }) => b.text)).toEqual(["B", "A"]);
    expect(button("+ Produtos do carrinho")).toBeUndefined();
  });

  it("HTML: importa arquivo .html e mostra o relatório", async () => {
    const onChange = vi.fn();
    const report = { bytes: 110_000, too_big: false, gmail_clip: true, full_document: true, variables: ["primeiro_nome"], has_unsubscribe: false, removed_unsafe: true };
    await act(async () => { root.render(<HtmlInput value="<html>x</html>" onChange={onChange} report={report} hint="Variáveis" />); });
    const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
    const file = new File(["<html><body>Oi</body></html>"], "black.html", { type: "text/html" });
    Object.defineProperty(input, "files", { value: [file] });
    await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); await new Promise((r) => setTimeout(r, 0)); });
    expect(onChange).toHaveBeenCalledWith("<html><body>Oi</body></html>");
    expect(host.textContent).toContain("documento completo");
    expect(host.textContent).toContain("o Gmail corta");
    expect(host.textContent).toContain("adicionado automaticamente no rodapé");
  });

  it("HTML: recusa arquivo que não é .html", async () => {
    const onChange = vi.fn();
    await act(async () => { root.render(<HtmlInput value="" onChange={onChange} hint="x" />); });
    const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, "files", { value: [new File(["x"], "foto.png", { type: "image/png" })] });
    await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(onChange).not.toHaveBeenCalled();
    expect(host.textContent).toContain("Escolha um arquivo .html");
  });

  it("carrinho: alterna para HTML próprio", async () => {
    await act(async () => { root.render(<CartRecoveryPanel canEdit />); });
    await flush();
    await act(async () => { button("HTML próprio").click(); });
    expect(host.querySelector('[aria-label="HTML do e-mail"]')).not.toBeNull();
    expect(host.textContent).toContain("{{produtos}} insere os itens do carrinho");
  });

  it("fluxos: mostra resultado por fluxo e liga um fluxo", async () => {
    api.getFlows.mockResolvedValue(FLOWS_FIXTURE);
    api.previewFlow.mockResolvedValue({ subject: "x", html: "<p>x</p>" });
    api.saveFlow.mockImplementation(async (_kind, patch) => ({ flow: { ...FLOWS_FIXTURE.flows[3], ...patch } }));
    await act(async () => { root.render(<FlowsPanel canEdit />); });
    await flush();
    expect(host.textContent).toContain("7.412,60");
    expect(host.textContent).toContain("9,2%");
    const links = [...host.querySelectorAll<HTMLButtonElement>(".emFlow > .emLink")];
    await act(async () => { links[3].click(); });
    await act(async () => { button("Salvar e ligar").click(); });
    expect(api.saveFlow.mock.calls[0][0]).toBe("reativacao");
    expect(api.saveFlow.mock.calls[0][1].enabled).toBe(true);
    expect(host.textContent).toContain("Fluxo ligado e salvo.");
  });
});
