import { describe, expect, it } from "vitest";
import { addDays, mondayOf } from "./studioCalendar";

describe("datas do calendário", () => {
  it("semana começa na segunda e atravessa mês/ano", () => {
    expect(mondayOf("2026-11-01")).toBe("2026-10-26"); // domingo → segunda anterior
    expect(mondayOf("2026-11-02")).toBe("2026-11-02");
    expect(addDays("2026-12-29", 7)).toBe("2027-01-05");
  });
});
