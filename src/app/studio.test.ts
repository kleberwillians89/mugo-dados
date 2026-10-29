import { describe, expect, it } from "vitest";
import { localParts, textToList, toSaoPauloIso } from "./studio";

describe("studio helpers", () => {
  it("monta horário de São Paulo e lê de volta no mesmo fuso", () => {
    const iso = toSaoPauloIso("2026-11-03", "19:00");
    expect(iso).toBe("2026-11-03T19:00:00-03:00");
    expect(localParts(iso)).toMatchObject({ date: "2026-11-03", time: "19:00" });
    // 22h em SP é o dia seguinte em UTC, mas continua 3/11 na tela.
    expect(localParts("2026-11-04T01:00:00+00:00").date).toBe("2026-11-03");
  });
  it("converte listas digitadas com vírgula ou quebra de linha", () => {
    expect(textToList("a, b\n c,, ")).toEqual(["a", "b", "c"]);
  });
});
