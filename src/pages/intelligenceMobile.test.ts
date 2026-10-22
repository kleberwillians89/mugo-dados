import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * Contrato de layout da Intelligence e do contexto estratégico.
 *
 * jsdom não calcula layout, então 375/390/430px não podem ser medidos aqui —
 * isso continua sendo verificação visual no navegador. O que dá para travar é
 * a regra que causa overflow e texto ilegível: coluna única por padrão,
 * `min-width:0` em filho de grid, quebra de palavra longa e nenhuma largura
 * fixa em px nos blocos novos.
 */

const intelligence = readFileSync("src/styles/intelligence.css", "utf8");
const companies = readFileSync("src/styles/companies.css", "utf8");

function block(css: string, selector: string) {
  const index = css.indexOf(selector);
  expect(index, `seletor ausente: ${selector}`).toBeGreaterThan(-1);
  return css.slice(index, css.indexOf("}", index) + 1);
}

describe("Intelligence — layout mobile-first", () => {
  // Compara sem espaços: o contrato é a regra, não a formatação do arquivo.
  const css = intelligence.replace(/\s+/g, "");

  it("listas e grades nascem em coluna única e só expandem com min-width", () => {
    for (const selector of [".intelMovement{", ".intelActionGroup{", ".intelInsight{", ".intelCrossList{", ".intelResearchItem{"]) {
      expect(block(css, selector), selector).toContain("grid-template-columns:1fr");
    }
    expect(css).toContain("@media(min-width:760px)");
    expect(css).toContain("@media(min-width:900px)");
  });

  it("filhos de grid podem encolher, evitando overflow horizontal", () => {
    expect(block(css, ".intelligencePage*{")).toContain("min-width:0");
    for (const selector of [".intelMovement{", ".intelMovementBody{", ".intelResearchItem{", ".intelActionGroup{", ".intelInsight{"]) {
      expect(block(css, selector), selector).toContain("min-width:0");
    }
  });

  it("texto longo quebra em vez de esticar a página", () => {
    expect(block(css, ".intelMovementBodyp{")).toContain("overflow-wrap:anywhere");
    expect(css).toContain(".intelligencePage:is(p,li,h1,h2,h3,h4,dd){overflow-wrap:anywhere;}");
  });

  it("nenhuma largura fixa em px nos blocos base", () => {
    for (const selector of [".intelMovement{", ".intelMovementList{", ".intelMetricGrid{", ".intelActionGroup{", ".intelInsight{"]) {
      expect(block(css, selector), selector).not.toMatch(/(?<!min-|max-)width:\d+px/);
    }
  });

  it("texto da leitura não é minúsculo", () => {
    const sizes = [...css.matchAll(/\.intel(?:Movement|Action|Insight|Metric)[^{]*\{[^}]*font-size:(\d+)px/g)]
      .map((match) => Number(match[1]));
    expect(sizes.length).toBeGreaterThan(0);
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(11);
  });
});

describe("Contexto estratégico — layout mobile-first", () => {
  it("formulário começa em uma coluna e só vira duas no desktop", () => {
    expect(block(companies, ".businessContextForm{")).toContain("grid-template-columns:1fr");
    expect(companies).toContain("@media(min-width:900px)");
  });

  it("área de texto respeita a largura disponível", () => {
    const rule = block(companies, ".businessContextForm textarea{");
    expect(rule).toContain("width:100%");
    expect(rule).toContain("box-sizing:border-box");
  });
});

describe("Acessos — layout mobile-first", () => {
  it("formulário começa em uma coluna e só vira duas acima de 760px", () => {
    expect(block(companies, ".accessForm{")).toContain("grid-template-columns:1fr");
    expect(companies).toContain("@media(min-width:760px)");
  });

  it("campos não estouram a largura disponível", () => {
    const rule = block(companies, ".accessForm input,.accessForm select{");
    expect(rule).toContain("width:100%");
    expect(rule).toContain("box-sizing:border-box");
    expect(block(companies, ".accessForm label{")).toContain("min-width:0");
  });

  it("ações embrulham em vez de cortar no celular", () => {
    expect(block(companies, ".accessFormActions{")).toContain("flex-wrap:wrap");
  });

  it("tabela de acessos continua rolável sem estourar a página", () => {
    // .companiesTableWrap já isola o scroll horizontal da tabela.
    expect(companies).toContain(".companiesTableWrap{overflow-x:auto");
  });
});
