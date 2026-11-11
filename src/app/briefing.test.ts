import { describe, expect, it } from "vitest";
import { briefingText } from "./studio";

describe("Briefing da peça", () => {
  it("monta o texto para copiar com ângulo, objetivo, mensagem, roteiro e arte", () => {
    const text = briefingText({ title: "Bastidor da curadoria", format: "reels", hook: "Você já viu como nasce um split?",
      script: "Cena 1: frasco na bancada\nCena 2: decant", visual_idea: "Luz natural, fundo claro",
      signals: { briefing: { objective: "Gerar conversa", key_message: "Split é o original fracionado", angle: "bastidor" } } });
    expect(text).toBe("PAUTA: Bastidor da curadoria\n\nFORMATO: reels\n\nÂNGULO: Bastidor\n\nOBJETIVO: Gerar conversa\n\n"
      + "MENSAGEM CENTRAL: Split é o original fracionado\n\nGANCHO: Você já viu como nasce um split?\n\n"
      + "ROTEIRO:\nCena 1: frasco na bancada\nCena 2: decant\n\nDIREÇÃO DA ARTE:\nLuz natural, fundo claro");
  });
  it("pauta antiga sem briefing não quebra", () => {
    expect(briefingText({ title: "Pauta", format: "imagem", hook: null, script: null, visual_idea: null, signals: {} })).toBe("PAUTA: Pauta\n\nFORMATO: imagem");
  });
});
