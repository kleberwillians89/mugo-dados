// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getClipping: vi.fn(), getClippingInsights: vi.fn(), getClippingReport: vi.fn(), exportClipping: vi.fn(), refreshClipping: vi.fn(), saveClippingSettings: vi.fn(), setClippingStatus: vi.fn(), clippingToCalendar: vi.fn(),
  listCampaigns: vi.fn(), getCampaign: vi.fn(), createCampaign: vi.fn(), regeneratePiece: vi.fn(), editPiece: vi.fn(), setCampaignStatus: vi.fn(), campaignToCalendar: vi.fn(),
  listMatrices: vi.fn(), getMatrix: vi.fn(), createMatrix: vi.fn(), archiveMatrix: vi.fn(), updateOpportunity: vi.fn(), refineOpportunity: vi.fn(),
  setOpportunitiesStatus: vi.fn(), matrixToCalendar: vi.fn(),
}));
const studioApi = vi.hoisted(() => ({ getBrandProfile: vi.fn() }));
vi.mock("../app/contentOps", async (original) => ({ ...(await original<typeof import("../app/contentOps")>()), ...api }));
vi.mock("../app/studio", async (original) => ({ ...(await original<typeof import("../app/studio")>()), ...studioApi }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("./Calendar", () => ({ default: () => <label>Calendário incorporado<input aria-label="Rascunho local do calendário" defaultValue="" /></label> }));

import Clipping from "./Clipping";
import Campaigns from "./Campaigns";
import { pieceText } from "../app/contentOps";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { window.history.replaceState({}, "", "/social-media"); api.getClippingInsights?.mockResolvedValue(null); api.listMatrices.mockResolvedValue({ matrices: [] }); api.listCampaigns.mockResolvedValue({ campaigns: [] });
  studioApi.getBrandProfile.mockResolvedValue({ profile: { pillars: [{ name: "Produto", weight: 60, description: "" }, { name: "Bastidores", weight: 40, description: "" }] }, saved: true }); host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); window.history.replaceState({}, "", "/"); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };

const week = { current: { total: 5, marca: 4, concorrente: 1, positivo: 2, neutro: 1, negativo: 1 }, previous: { total: 2, marca: 2, concorrente: 0, positivo: 1, neutro: 1, negativo: 0 }, marca_variacao: 2 };

describe("Clipping", () => {
  it("sem termos, pede a configuração", async () => {
    api.getClipping.mockResolvedValue({ items: [], week, settings: { brand_terms: [], competitor_terms: [], exclude_terms: [], active: true, last_run_at: null, saved: false } });
    await show(<Clipping canManage />);
    expect(host.textContent).toContain("Configure os termos");
  });

  it("mostra o resumo da semana e cada notícia com fonte e leitura da IA", async () => {
    api.getClipping.mockResolvedValue({ week, settings: { brand_terms: ["Curavino"], competitor_terms: [], exclude_terms: [], active: true, last_run_at: null, saved: true },
      items: [{ id: "n1", url: "https://news/1", title: "Curavino lança linha natural", source: "Revista Adega", published_at: "2026-10-28T12:00:00Z", kind: "marca", term: "Curavino", sentiment: "positivo", summary: "Lançamento bem recebido", relevant: true, status: "novo", calendar_item_id: null, created_at: "2026-10-28T12:00:00Z" }] });
    await show(<Clipping canManage />);
    expect(host.textContent).toContain("menções da marca em 7 dias");
    expect(host.textContent).toContain("+2 vs. semana anterior");
    expect(host.querySelector('a[href="https://news/1"]')?.textContent).toContain("Curavino lança linha natural");
    expect(host.textContent).toContain("Positiva");
    expect(host.textContent).toContain("Virar pauta");
  });

  it("cliente lê as notícias sem termos nem ações", async () => {
    api.getClipping.mockResolvedValue({ week, settings: { saved: true, last_run_at: null },
      items: [{ id: "n1", url: "https://news/1", title: "Curavino lança linha natural", source: "Revista Adega", published_at: "2026-10-28T12:00:00Z", kind: "marca", term: "Curavino", sentiment: "positivo", summary: null, relevant: true, status: "novo", calendar_item_id: null, created_at: "2026-10-28T12:00:00Z" }] });
    await show(<Clipping />);
    expect(host.textContent).toContain("Curavino lança linha natural");
    for (const action of ["Virar pauta", "Arquivar", "Termos", "Atualizar agora"]) expect(host.textContent).not.toContain(action);
  });

  it("painel mostra alerta crítico, marca x concorrentes e relatório só para a agência", async () => {
    api.getClipping.mockResolvedValue({ items: [], week, settings: { brand_terms: ["Curavino"], competitor_terms: ["Evino"], exclude_terms: [], active: true, last_run_at: null, saved: true } });
    api.getClippingInsights.mockResolvedValue({ total: 3, analyzed: 3, sentiment: [{ key: "negativo", count: 2 }], themes: [{ key: "varejo", count: 2 }],
      sources: [{ key: "G1", count: 2 }], mentions: [{ key: "marca:Curavino", count: 2 }, { key: "concorrente:Evino", count: 1 }],
      timeline: [{ day: "2026-10-29", count: 1 }, { day: "2026-10-30", count: 2 }],
      critical: [{ id: "c1", title: "Recall de vinho", url: "https://g1/x", source: "G1", published_at: null, criticality: "critica", relevance: 90, sentiment: "negativo", risks: [] }] });
    await show(<Clipping canManage />);
    expect(host.textContent).toContain("1 matéria(s) crítica(s) aguardando revisão");
    expect(host.textContent).toContain("Evino (Concorrente)");
    expect(host.textContent).toContain("Gerar relatório");
    await act(async () => { root.render(<Clipping />); }); await act(async () => {});
    expect(host.textContent).not.toContain("Gerar relatório");
    expect(host.textContent).not.toContain("Exportar CSV");
  });

  it("cliente sem clipping ativo não vê convite para configurar", async () => {
    api.getClipping.mockResolvedValue({ items: [], week, settings: { saved: false, last_run_at: null } });
    await show(<Clipping />);
    expect(host.textContent).toContain("ainda não foi ativado pela Mugô");
    expect(host.textContent).not.toContain("Configure os termos");
  });
});

const tab = (label: string) => [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((b) => b.textContent?.startsWith(label))!;

describe("Social Media: Campanhas (antes Redação)", () => {
  it("abre a campanha com contador de caracteres e alerta acima do limite", async () => {
    api.listCampaigns.mockResolvedValue({ campaigns: [{ id: "c1", name: "Black Friday", status: "rascunho", briefing: { objective: "vender" }, calendar_item_ids: [] }] });
    api.getCampaign.mockResolvedValue({ campaign: { id: "c1", name: "Black Friday", status: "rascunho", briefing: {}, calendar_item_ids: [], updated_at: "x",
      package: { concept: { nome: "Presente certo", ideia: "Oud como presente", por_que: "Oud vendeu 40% em outubro" }, titles: ["A"], generated_at: "x",
        pieces: { google_ads: { channel: "google_ads", label: "Anúncio Google", content: { titulos: ["Oud na Black Friday", "Um título longo demais para o Google Ads"], descricoes: ["Frete grátis"] },
          limits: [{ field: "titulos", index: 0, length: 19, limit: 30, over: false }, { field: "titulos", index: 1, length: 39, limit: 30, over: true }, { field: "descricoes", index: 0, length: 12, limit: 90, over: false }], flags: [] } } } } });
    await show(<Campaigns />);
    expect(host.textContent).toContain("Social Media");
    await act(async () => { tab("Criação").click(); }); await act(async () => {});
    const button = [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Black Friday"))!;
    await act(async () => { button.click(); }); await act(async () => {});
    expect(host.textContent).toContain("Presente certo");
    expect(host.textContent).toContain("1 texto(s) acima do limite");
    expect(host.textContent).toContain("40/30"); // contador conta o texto da tela, não o que a IA disse
    expect(host.querySelector(".pieceLabel em.is-over")).not.toBeNull();
  });

  it("texto para copiar sai na ordem da plataforma", () => {
    expect(pieceText("google_ads", { titulos: ["T1", "T2"], descricoes: ["D1"] })).toBe("Títulos:\nT1\nT2\n\nDescrições:\nD1");
    expect(pieceText("email", { assunto: "A", preheader: "P", corpo: "C" })).toBe("Assunto: A\nPré-cabeçalho: P\n\nC");
  });

  it("campanha exportada abre a aba Calendário existente", async () => {
    const campaign = { id: "c1", name: "Black Friday", status: "pronta", briefing: {}, calendar_item_ids: [], updated_at: "x", package: { concept: { nome: "Conceito", ideia: "Ideia", por_que: "Motivo" }, titles: [], pieces: {} } };
    api.listCampaigns.mockResolvedValue({ campaigns: [campaign] });
    api.getCampaign.mockResolvedValue({ campaign });
    api.campaignToCalendar.mockResolvedValue({ created: 1, already: false, calendar_item_ids: ["item-1"] });
    await show(<Campaigns />);
    await act(async () => { tab("Criação").click(); }); await act(async () => {});
    await act(async () => { [...host.querySelectorAll("button")].find((button) => button.textContent?.includes("Black Friday"))!.click(); }); await act(async () => {});
    await act(async () => { byText("Mandar pro Calendário").click(); }); await act(async () => {});
    await act(async () => { byText("Abrir o Calendário").click(); }); await act(async () => {});
    expect(tab("Calendário").getAttribute("aria-selected")).toBe("true");
    expect(api.campaignToCalendar).toHaveBeenCalledWith("c1");
  });
});

const opp = (id: string, extra: Record<string, unknown> = {}) => ({ id, matrix_id: "m1", platform: "instagram", pillar: "Produto", week: 1, weekday: 2,
  format: "reels", title: `Pauta ${id}`, hook: "Gancho", angle: null, caption_draft: "Legenda", rationale: null, guard: [], status: "sugerida",
  edited: false, position: 0, calendar_item_id: null, ...extra });
const matrix = (ops: ReturnType<typeof opp>[]) => ({ id: "m1", week_start: "2026-11-16", platforms: ["instagram", "tiktok"], pillars: [{ name: "Produto" }, { name: "Bastidores" }],
  focus: null, summary: "Mês do lançamento.", status: "ativa", created_at: "x", notes: [], opportunities: ops });
const byText = (text: string) => [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === text)!;

describe("Social Media: Matriz de conteúdo", () => {
  it("abre na Matriz, organizada por pilar e 4 semanas, com filtro por plataforma", async () => {
    api.listMatrices.mockResolvedValue({ matrices: [matrix([])] });
    api.getMatrix.mockResolvedValue({ matrix: matrix([opp("a"), opp("b", { platform: "tiktok", format: "video", week: 3, pillar: "Bastidores" })]) });
    await show(<Campaigns />);
    expect(tab("Matriz de Conteúdo").getAttribute("aria-selected")).toBe("true");
    expect(host.textContent).toContain("Mês do lançamento.");
    expect(host.querySelectorAll(".matrixGrid thead th").length).toBe(5); // pilar + 4 semanas
    expect(host.textContent).toContain("16/11 a 22/11");
    expect(host.querySelectorAll(".matrixCard").length).toBe(2);
    await act(async () => { tab("TikTok").click(); }); await act(async () => {});
    expect([...host.querySelectorAll(".matrixCard")].map((c) => c.getAttribute("aria-label"))).toEqual(["Pauta b"]);
  });

  it("gera a matriz com plataformas, pilares e semana inicial", async () => {
    api.createMatrix.mockResolvedValue({ matrix: matrix([opp("a")]) });
    await show(<Campaigns />);
    await act(async () => { byText("Gerar matriz").click(); }); await act(async () => {});
    const tiktok = [...document.querySelectorAll<HTMLLabelElement>(".studioForm fieldset label")].find((l) => l.textContent === "TikTok")!;
    await act(async () => { tiktok.querySelector("input")!.click(); });
    const submit = [...document.querySelectorAll<HTMLButtonElement>(".studioForm button")].find((b) => b.textContent === "Gerar matriz")!;
    await act(async () => { submit.click(); }); await act(async () => {});
    const input = api.createMatrix.mock.calls[0][0];
    expect(input.platforms).toEqual(["instagram", "tiktok"]);
    expect(input.week_start).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(host.querySelectorAll(".matrixCard").length).toBe(1);
  });

  it("seleciona, descarta e envia ao Calendário sem reenviar o que já foi", async () => {
    api.listMatrices.mockResolvedValue({ matrices: [matrix([])] });
    api.getMatrix.mockResolvedValue({ matrix: matrix([opp("a"), opp("b"), opp("c", { status: "exportada", calendar_item_id: "i1" })]) });
    api.updateOpportunity.mockImplementation(async (_m: string, id: string, patch: { status: string }) => ({ opportunity: opp(id, { status: patch.status }) }));
    api.matrixToCalendar.mockResolvedValue({ created: 1, already: 0, calendar_item_ids: ["i2"],
      matrix: matrix([opp("a", { status: "exportada", calendar_item_id: "i2" }), opp("b", { status: "descartada" }), opp("c", { status: "exportada", calendar_item_id: "i1" })]) });
    await show(<Campaigns />);
    const card = (id: string) => [...host.querySelectorAll(".matrixCard")].find((c) => c.getAttribute("aria-label") === `Pauta ${id}`)!;
    expect(card("c").textContent).toContain("No Calendário");
    expect(card("c").querySelector('input[type="checkbox"]')).toBeNull(); // exportada não volta a ser selecionada
    expect(byText("Enviar ao Calendário").disabled).toBe(true);
    await act(async () => { card("a").querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(); }); await act(async () => {});
    expect(api.updateOpportunity).toHaveBeenCalledWith("m1", "a", { status: "selecionada" });
    const discard = [...card("b").querySelectorAll("button")].find((b) => b.textContent === "Descartar")!;
    await act(async () => { discard.click(); }); await act(async () => {});
    expect(card("b")).toBeUndefined(); // descartada some da grade
    await act(async () => { byText("Enviar ao Calendário").click(); }); await act(async () => {});
    expect(api.matrixToCalendar).toHaveBeenCalledWith("m1");
    expect(host.textContent).toContain("1 conteúdo(s) no Calendário como rascunho");
    await act(async () => { byText("Abrir o Calendário").click(); }); await act(async () => {});
    expect(tab("Calendário").getAttribute("aria-selected")).toBe("true");
  });

  it("sem permissão de alterar, só lê", async () => {
    api.listMatrices.mockResolvedValue({ matrices: [matrix([])] });
    api.getMatrix.mockResolvedValue({ matrix: matrix([opp("a")]) });
    await show(<Campaigns canManage={false} />);
    expect(byText("Gerar matriz")).toBeUndefined();
    expect(byText("Enviar ao Calendário")).toBeUndefined();
    expect(host.querySelector('.matrixCard input[type="checkbox"]')).toBeNull();
  });

  it("sem pilares no Perfil de Marca, avisa antes de gerar", async () => {
    studioApi.getBrandProfile.mockResolvedValue({ profile: { pillars: [] }, saved: true });
    await show(<Campaigns />);
    expect(host.textContent).toContain("ainda não tem pilares editoriais");
  });
});

describe("Social Media unificado", () => {
  it("mantém Matriz, Criação e Calendário na mesma página sem perder o estado montado", async () => {
    await show(<Campaigns />);
    expect(tab("Matriz de Conteúdo").getAttribute("aria-selected")).toBe("true");
    await act(async () => { tab("Calendário").click(); }); await act(async () => {});
    const draft = host.querySelector<HTMLInputElement>('input[aria-label="Rascunho local do calendário"]')!;
    draft.value = "edição preservada";
    await act(async () => { tab("Criação").click(); }); await act(async () => {});
    await act(async () => { tab("Calendário").click(); }); await act(async () => {});
    expect(host.querySelector<HTMLInputElement>('input[aria-label="Rascunho local do calendário"]')?.value).toBe("edição preservada");
    expect(window.location.pathname).toBe("/social-media");
    expect(new URLSearchParams(window.location.search).get("aba")).toBe("calendario");
  });

  it("usuário com somente Calendário não recebe acesso às abas de Matriz ou Criação", async () => {
    await show(<Campaigns canViewSocial={false} canViewCalendar canManageCalendar={false} initialTab="calendario" />);
    expect(tab("Calendário").getAttribute("aria-selected")).toBe("true");
    expect(tab("Matriz de Conteúdo")).toBeUndefined();
    expect(tab("Criação")).toBeUndefined();
    expect(host.textContent).toContain("Calendário incorporado");
  });

  it("links legados abrem a aba correspondente", async () => {
    window.history.replaceState({}, "", "/redacao");
    await show(<Campaigns />);
    expect(tab("Criação").getAttribute("aria-selected")).toBe("true");
    await act(async () => root.unmount());
    root = createRoot(host);
    window.history.replaceState({}, "", "/calendario");
    await show(<Campaigns />);
    expect(tab("Calendário").getAttribute("aria-selected")).toBe("true");
  });
});
