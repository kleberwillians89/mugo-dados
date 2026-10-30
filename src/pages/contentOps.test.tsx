// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getClipping: vi.fn(), refreshClipping: vi.fn(), saveClippingSettings: vi.fn(), setClippingStatus: vi.fn(), clippingToCalendar: vi.fn(),
  listCampaigns: vi.fn(), getCampaign: vi.fn(), createCampaign: vi.fn(), regeneratePiece: vi.fn(), editPiece: vi.fn(), setCampaignStatus: vi.fn(), campaignToCalendar: vi.fn(),
}));
vi.mock("../app/contentOps", async (original) => ({ ...(await original<typeof import("../app/contentOps")>()), ...api }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));

import Clipping from "./Clipping";
import Campaigns from "./Campaigns";
import { pieceText } from "../app/contentOps";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
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

  it("cliente sem clipping ativo não vê convite para configurar", async () => {
    api.getClipping.mockResolvedValue({ items: [], week, settings: { saved: false, last_run_at: null } });
    await show(<Clipping />);
    expect(host.textContent).toContain("ainda não foi ativado pela Mugô");
    expect(host.textContent).not.toContain("Configure os termos");
  });
});

describe("Redação", () => {
  it("abre a campanha com contador de caracteres e alerta acima do limite", async () => {
    api.listCampaigns.mockResolvedValue({ campaigns: [{ id: "c1", name: "Black Friday", status: "rascunho", briefing: { objective: "vender" }, calendar_item_ids: [] }] });
    api.getCampaign.mockResolvedValue({ campaign: { id: "c1", name: "Black Friday", status: "rascunho", briefing: {}, calendar_item_ids: [], updated_at: "x",
      package: { concept: { nome: "Presente certo", ideia: "Oud como presente", por_que: "Oud vendeu 40% em outubro" }, titles: ["A"], generated_at: "x",
        pieces: { google_ads: { channel: "google_ads", label: "Anúncio Google", content: { titulos: ["Oud na Black Friday", "Um título longo demais para o Google Ads"], descricoes: ["Frete grátis"] },
          limits: [{ field: "titulos", index: 0, length: 19, limit: 30, over: false }, { field: "titulos", index: 1, length: 39, limit: 30, over: true }, { field: "descricoes", index: 0, length: 12, limit: 90, over: false }], flags: [] } } } } });
    await show(<Campaigns />);
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
});
