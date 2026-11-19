import { describe, expect, it } from "vitest";
import { clippingHeadline } from "./clippingText";

const week = (marca: number, positivo: number, negativo: number, variacao: number, concorrente = 0) => ({
  current: { marca, positivo, neutro: marca - positivo - negativo, negativo, concorrente },
  previous: { marca: marca - variacao, positivo: 0, neutro: 0, negativo: 0, concorrente: 0 }, marca_variacao: variacao,
}) as never;

describe("primeira frase do Clipping", () => {
  it("resume a semana em português", () => {
    expect(clippingHeadline("Roove", week(5, 3, 1, 2))).toBe("Nos últimos 7 dias, a Roove apareceu em 5 notícias (3 positivas e 1 negativa), 2 a mais que na semana anterior.");
    expect(clippingHeadline("Roove", week(0, 0, 0, 0, 4))).toBe("Nenhuma notícia sobre a Roove nos últimos 7 dias. Os concorrentes apareceram em 4.");
  });
});
