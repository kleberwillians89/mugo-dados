import { describe, expect, it } from "vitest";
import { salesOriginHeadline, siteHeadline } from "./plainHeadlines";

describe("frases de resultado", () => {
  it("vendas por origem", () => {
    expect(salesOriginHeadline({ orders: 40, revenue: 12000, origin_coverage_percent: 72.4 })).toMatch(/40 pedidos, somando R\$\s?12\.000,00\. Sabemos de onde veio 72% deles\./);
    expect(salesOriginHeadline({ orders: 0, revenue: 0 })).toBe("Nenhum pedido na loja neste período.");
  });
  it("site", () => {
    expect(siteHeadline({ sessions: 2000, purchases: 30, purchase_revenue: 9000 })).toMatch(/2\.000 visitas e 30 compras \(R\$\s?9\.000,00\): de cada 100 visitas, 1,5 compraram\./);
    expect(siteHeadline({ sessions: 0 })).toMatch(/não recebeu visitas/);
  });
});
