import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { STAGES, STAGE_STATUS, STUDIO_STATUS, basedOnText } from "./studio";
import { curvePoints, money, outcomeFor, percent, project } from "./media";
import AiAssist from "../components/studio/AiAssist";

describe("inteligência de conteúdo", () => {
  it("explica em que dados a IA se baseou e admite quando faltam", () => {
    expect(basedOnText({ kpis: 3, campanhas: 2, posts_analisados: 40, metas: 0, aprovados: 5, ajustes: 1, lacunas: [] }))
      .toBe("Com base em 40 posts analisados, 5 pauta(s) aprovada(s), 1 ajuste(s) pedido(s), 2 campanha(s), 3 KPI(s).");
    expect(basedOnText({ kpis: 0, campanhas: 0, posts_analisados: 0, metas: 0, aprovados: 0, ajustes: 0, lacunas: ["sem_kpis_no_periodo"] }))
      .toMatch(/Sem dados suficientes/);
  });

  it("o painel de IA aparece com as ações e só oferece roteiro para formatos de vídeo", () => {
    const base = { title: "Lançamento", pillar: "", hook: "", caption_draft: "" };
    const reels = renderToStaticMarkup(<AiAssist draft={{ ...base, format: "reels" }} onApply={() => undefined} />);
    const feed = renderToStaticMarkup(<AiAssist draft={{ ...base, format: "carrossel" }} onApply={() => undefined} />);
    expect(reels).toContain("Roteiro de Reels");
    expect(feed).not.toContain("Roteiro de Reels");
    expect(feed).toContain("Legenda final");
    expect(renderToStaticMarkup(<AiAssist draft={{ ...base, title: " ", format: "imagem" }} onApply={() => undefined} />)).toContain("Dê um título");
  });
});

describe("funil de aprovação", () => {
  it("cada coluna arrastável grava um status válido; 'com o cliente' só pelo envio do link", () => {
    expect(Object.keys(STAGES)).toEqual(["rascunho", "revisao_interna", "com_cliente", "ajuste", "aprovado", "publicado"]);
    expect(STAGE_STATUS.com_cliente).toBeUndefined();
    for (const status of Object.values(STAGE_STATUS)) expect(Object.keys(STUDIO_STATUS)).toContain(status);
  });
});

describe("Mídia On", () => {
  it("projeta com a mesma fórmula do backend (y = a·gasto_semanal^b × semanas)", () => {
    const curve = { a: 10, b: 0.7, fit: "medida" as const, r2: 0.8, points: 13 };
    const weeks = 30 / 7;
    expect(project(curve, 3000, 30)).toBeCloseTo(10 * (3000 / weeks) ** 0.7 * weeks, 6);
    expect(project(curve, 0, 30)).toBe(0);
    // retorno decrescente: dobrar a verba não dobra o resultado
    expect(project(curve, 6000, 30)).toBeLessThan(2 * project(curve, 3000, 30));
  });

  it("recalcula a divisão ajustada pela equipe e soma os canais", () => {
    const c = (a: number) => ({ a, b: 0.7, fit: "medida" as const, r2: 0.8, points: 13 });
    const curves = { meta: { revenue: c(50), conversions: c(1), clicks: c(20), impressions: c(900) }, google_ads: { revenue: c(30), conversions: c(0.6), clicks: c(10), impressions: c(400) } };
    const out = outcomeFor(curves, { meta: 2000, google_ads: 1000 }, 30);
    expect(out.totals.spend).toBe(3000);
    expect(out.totals.revenue).toBeCloseTo((out.channels.meta?.revenue || 0) + (out.channels.google_ads?.revenue || 0), 6);
    expect(out.totals.roas).toBeCloseTo(out.totals.revenue / 3000, 6);
    expect(curvePoints(curves.meta.revenue, 2000, 30, 10)).toHaveLength(11);
  });

  it("formata valores", () => {
    expect(money(null)).toBe("—");
    expect(money(1500)).toMatch(/R\$\s?1\.500/);
    expect(percent(0.0123, 2)).toBe("1,23%");
  });
});
