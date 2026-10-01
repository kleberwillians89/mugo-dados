import { describe, expect, it } from "vitest";
import {
  formatCalendarDate,
  formatCalendarDateWords,
  formatCurrency,
  formatCurrencyAxis,
  formatCurrencyShort,
  formatDateTimeSaoPaulo,
  formatPercentNumber,
  uniquePeak,
} from "./dataFormat";

const plain = (value: string) => value.replace(/\u00a0/g, " ");

describe("dataFormat — leitura de dados pt-BR", () => {
  it("datas de calendário não sofrem conversão de fuso (sem deslocar o dia)", () => {
    expect(formatCalendarDate("2026-09-01")).toBe("01/09");
    expect(formatCalendarDate("2026-09-01", "long")).toBe("01/09/2026");
    expect(formatCalendarDate("2026-09-01", "month")).toBe("set/26");
  });

  it("abrevia valores grandes e preserva o exato", () => {
    expect(plain(formatCurrencyShort(48_320))).toBe("R$ 48,3 mil");
    expect(plain(formatCurrencyShort(1_234_567))).toBe("R$ 1,2 mi");
    expect(plain(formatCurrencyShort(298.45))).toBe("R$ 298");
    expect(plain(formatCurrencyShort(12.5))).toBe("R$ 12,50");
    expect(plain(formatCurrencyShort(0))).toBe("R$ 0");
    expect(plain(formatCurrency(48_320))).toBe("R$ 48.320,00");
    expect(plain(formatCurrencyAxis(4_000))).toBe("R$ 4 mil");
  });

  it("percentual com uma casa e data/hora no fuso comercial", () => {
    expect(formatPercentNumber(18.44)).toBe("18,4");
    expect(formatPercentNumber(25)).toBe("25");
    expect(formatDateTimeSaoPaulo("2026-09-30T17:20:00Z")).toBe("30/09/2026, 14:20");
  });

  it("data por extenso sem fuso e pico só quando é único", () => {
    expect(formatCalendarDateWords("2026-09-01")).toBe("1 de setembro");
    expect(formatCalendarDateWords("2026-09-01", "month")).toBe("setembro de 2026");
    const rows = [{ v: 3 }, { v: 9 }, { v: 4 }];
    expect(uniquePeak(rows, (row) => row.v)).toBe(rows[1]);
    expect(uniquePeak([{ v: 9 }, { v: 9 }], (row) => row.v)).toBeNull();
    expect(uniquePeak([{ v: 9 }], (row) => row.v)).toBeNull();
    expect(uniquePeak([{ v: 0 }, { v: 0 }], (row) => row.v)).toBeNull();
  });
});
