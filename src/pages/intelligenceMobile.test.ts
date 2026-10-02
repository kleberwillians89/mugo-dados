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
  it("listas de prioridade nascem em coluna única e só expandem acima de 760px", () => {
    expect(block(intelligence, ".intelMovementList{")).toContain("display:grid");
    expect(block(intelligence, ".intelOpportunityList,.intelIdeaList{")).toContain("grid-template-columns:1fr");
    expect(intelligence).toContain("@media(min-width:760px)");
  });

  it("filhos de grid podem encolher, evitando overflow horizontal", () => {
    for (const selector of [
      ".intelMovementBody{",
      ".intelOpportunityList>article,.intelIdeaList>article{",
      ".intelResearchItem{",
    ]) {
      expect(block(intelligence, selector), selector).toContain("min-width:0");
    }
  });

  it("texto longo quebra em vez de esticar a página", () => {
    expect(block(intelligence, ".intelMovementBody p{")).toContain("overflow-wrap:anywhere");
    expect(block(intelligence, ".intelOpportunityList p,.intelIdeaList p{")).toContain("overflow-wrap:anywhere");
  });

  it("nenhuma largura fixa em px nos blocos novos", () => {
    for (const selector of [".intelMovement{", ".intelMovementList{", ".intelIdeaList>article" ]) {
      const rule = block(intelligence, selector);
      expect(rule, selector).not.toMatch(/(?<!min-|max-)width:\s*\d+px/);
    }
  });

  it("texto dos cartões não é minúsculo", () => {
    const sizes = [...intelligence.matchAll(/\.intel(?:Movement|Opportunity|Idea)[^{]*\{[^}]*font-size:(\d+)px/g)]
      .map((match) => Number(match[1]));
    expect(sizes.length).toBeGreaterThan(0);
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(12);
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
