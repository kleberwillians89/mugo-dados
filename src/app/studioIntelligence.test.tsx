import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { STAGES, STAGE_STATUS, STUDIO_STATUS, basedOnText } from "./studio";
import { allocationTotal, money, percent } from "./media";
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
  it("soma a divisão e formata valores", () => {
    expect(allocationTotal({ meta: 60, google_ads: 40 })).toBe(100);
    expect(allocationTotal({ meta: 33.33, google_ads: 33.33 })).toBe(66.7);
    expect(money(null)).toBe("—");
    expect(money(1500)).toMatch(/R\$\s?1\.500/);
    expect(percent(0.0123)).toBe("1,23%");
  });
});
