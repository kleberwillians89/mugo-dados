import { describe, expect, it } from "vitest";
import { formatGoogleAdsAccountLabel, type GoogleAdsAccount } from "./api";

describe("formatGoogleAdsAccountLabel — nunca mostra apenas o ID cru", () => {
  it("mostra nome descritivo + ID formatado quando o nome está disponível", () => {
    const account: GoogleAdsAccount = { customer_id: "1234567890", descriptive_name: "Amalie" };
    expect(formatGoogleAdsAccountLabel(account)).toBe("Amalie — 123-456-7890");
  });

  it("usa fallback 'Conta {id-formatado}', nunca o ID cru sozinho, quando não há nome", () => {
    const account: GoogleAdsAccount = { customer_id: "1234567890" };
    const label = formatGoogleAdsAccountLabel(account);
    expect(label).toBe("Conta 123-456-7890");
    expect(label).not.toBe("1234567890");
  });
});
