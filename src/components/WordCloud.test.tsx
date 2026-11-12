// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import WordCloud from "./WordCloud";
import { wordTitle } from "../app/wordTone";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("Nuvem de palavras por sentimento", () => {
  it("pinta cada palavra com o tom dominante e mostra a legenda", async () => {
    const el = document.createElement("div");
    const root = createRoot(el);
    await act(async () => {
      root.render(<WordCloud words={[
        { word: "amei", count: 12, tone: "positivo", sentiment: { positivo: 10, sem_analise: 2 } },
        { word: "atraso", count: 5, tone: "negativo", sentiment: { negativo: 4, neutro: 1 } },
        { word: "tamanho", count: 3, tone: null, sentiment: { sem_analise: 3 } },
      ]} />);
    });
    expect(el.querySelector(".wordTag.is-positivo")?.textContent).toBe("amei");
    expect(el.querySelector(".wordTag.is-negativo")?.textContent).toBe("atraso");
    expect(el.querySelector(".wordTag.is-sem_analise")?.textContent).toBe("tamanho");
    expect(el.querySelector(".wordCloudLegend")?.textContent).toBe("PositivoNegativoSem análise");
    act(() => root.unmount());
  });

  it("dica com a divisão dos comentários", () => {
    expect(wordTitle({ word: "atraso", count: 5, tone: "negativo", sentiment: { negativo: 4, neutro: 1 } }))
      .toBe("atraso: 5 menções · 1 neutro, 4 negativos");
  });
});
