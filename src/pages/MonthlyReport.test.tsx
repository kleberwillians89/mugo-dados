// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const social = vi.hoisted(() => ({ getSocialReport: vi.fn(), buildSocialReport: vi.fn(), draftReportInsights: vi.fn(), saveReportInsights: vi.fn() }));
const monthly = vi.hoisted(() => ({ getMonthlyReport: vi.fn(), closeMonthlyReport: vi.fn(), saveMonthlySummary: vi.fn(),
  releaseMonthlyReport: vi.fn(), shareMonthlyReport: vi.fn() }));
vi.mock("../app/socialReport", async (original) => ({ ...(await original<typeof import("../app/socialReport")>()), ...social }));
vi.mock("../app/monthlyReport", async (original) => ({ ...(await original<typeof import("../app/monthlyReport")>()), ...monthly }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "roove", getActiveClientName: () => "Roove" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ controls }: { controls: React.ReactNode }) => <div>{controls}</div> }));

import SocialReport, { BusinessDeck } from "./SocialReport";
import { reportTokenFromPath } from "../app/monthlyReport";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim().startsWith(text)) as HTMLButtonElement;
const BIZ = { midia: { investimento: 1200, anuncios: 4, conversoes: 30, receita: 6000, roas: 5, custo_por_conversao: 40, comparado_por: "retorno (ROAS)",
  melhores: [{ anuncio: "Legging", campanha: "BF", investimento: 300, conversoes: 12, receita: 2400, roas: 8, ctr_pct: 2 }] },
  whatsapp: { conversas: 210, viraram_venda: 21, taxa_pct: 10, pedidos: 22, receita: 4100, parte_da_loja_pct: 12, origens: [] },
  vendas: { pedidos: 180, faturamento: 34000, ticket_medio: 188.9, pedidos_mes_anterior: 150, faturamento_mes_anterior: 29000, variacao_faturamento_pct: 17.2 } };

describe("Relatório mensal", () => {
  it("monta os slides de mídia, WhatsApp, vendas e resumo", async () => {
    await act(async () => { root.render(<BusinessDeck b={BIZ} summary={"Vendas subiram 17%\n\nPróximos passos:\nAumentar a verba do anúncio Legging"} month="2026-10" />); });
    const text = host.textContent?.replace(/\u00a0/g, " ") || "";
    expect(text).toContain("R$ 1.200investidos no Meta em 4 anúncios");
    expect(text).toContain("210conversas novas, 21 viraram venda (10%)");
    expect(text).toContain("(+17,2% contra o mês anterior)");
    expect(text).toContain("> Aumentar a verba do anúncio Legging");
  });

  it("equipe vê rascunho, libera e cria o link", async () => {
    social.getSocialReport.mockResolvedValue({ month: "2026-10", built: false });
    monthly.getMonthlyReport.mockResolvedValue({ exists: true, status: "rascunho", data: BIZ, summary: "ok" });
    monthly.releaseMonthlyReport.mockResolvedValue({ exists: true, status: "liberado", data: BIZ, summary: "ok", released_at: "2026-11-01T13:00:00Z" });
    monthly.shareMonthlyReport.mockResolvedValue({ share_token: "a".repeat(32) });
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    await act(async () => { root.render(<SocialReport isAgency />); });
    await act(async () => {});
    expect(host.textContent).toContain("Rascunho: o cliente ainda não vê este mês");
    await act(async () => { btn("Liberar para o cliente").click(); });
    expect(monthly.releaseMonthlyReport).toHaveBeenCalledWith(expect.any(String), true);
    await act(async () => { btn("Criar link").click(); });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining(`/relatorio/${"a".repeat(32)}`));
  });

  it("cliente vê aviso enquanto o mês está em revisão", async () => {
    social.getSocialReport.mockResolvedValue({ month: "2026-10", built: false, pending_release: true });
    monthly.getMonthlyReport.mockResolvedValue({ exists: true, status: "rascunho", hidden: true });
    await act(async () => { root.render(<SocialReport />); });
    await act(async () => {});
    expect(host.textContent).toContain("sendo revisado pela Mugô");
  });

  it("reconhece o link público", () => {
    expect(reportTokenFromPath(`/relatorio/${"a".repeat(32)}`)).toBe("a".repeat(32));
    expect(reportTokenFromPath("/relatorio/curto")).toBeNull();
  });
});
