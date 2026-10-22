import { describe, expect, it } from "vitest";
import { buildTechnicalLabels, humanizeAnalysisRecord, humanizeMessage, humanizeTechnicalText } from "./technicalText";
import type { IntelligenceAnalysisRecord, IntelligenceMessage } from "./intelligenceTypes";

const labels = buildTechnicalLabels([{ id: "orders", label: "Pedidos" }, { id: "new_customers", label: "Novos clientes" }]);

describe("humanizeTechnicalText", () => {
  it("troca a citação técnica da Roove pelos rótulos", () => {
    expect(humanizeTechnicalText("Vendas subiram. metric_ids: orders, new_customers", labels))
      .toBe("Vendas subiram. Pedidos, Novos clientes");
  });
  it("remove citação entre parênteses", () => {
    expect(humanizeTechnicalText("Vendas subiram (metric_ids: orders) no mês.", labels)).toBe("Vendas subiram no mês.");
  });
  it("troca identificador com sublinhado e crase", () => {
    expect(humanizeTechnicalText("Acompanhe `new_customers` e meta_ads.", labels)).toBe("Acompanhe Novos clientes e Meta Ads.");
  });
  it("não mexe em texto comum", () => {
    expect(humanizeTechnicalText("Faturamento estável com mais pedidos.", labels)).toBe("Faturamento estável com mais pedidos.");
  });
});

describe("registros e mensagens", () => {
  it("limpa a análise mantendo metric_ids", () => {
    const record = {
      metrics_snapshot: [{ id: "orders", label: "Pedidos" }],
      sources: [],
      analysis: {
        executive: { overall: "metric_ids: orders", main_change: "", opportunity: "", attention: "", priority_action: "" },
        insights: [{ category: "positive", title: "new_customers", interpretation: "x", metric_ids: ["orders"], sources: [], impact: "low", confidence: "low", action: "a", reason: "r" }],
        actions: [],
      },
    } as unknown as IntelligenceAnalysisRecord;
    const out = humanizeAnalysisRecord(record)!;
    expect(out.analysis!.executive.overall).toBe("Pedidos");
    expect(out.analysis!.insights[0].title).toBe("Novos clientes");
    expect(out.analysis!.insights[0].metric_ids).toEqual(["orders"]);
  });
  it("limpa resposta do assistente e preserva a pergunta", () => {
    const message = { id: "1", role: "assistant", content: { direct_answer: "Subiu (sources: meta_ads).", evidence: ["new_customers ok"] } } as unknown as IntelligenceMessage;
    const out = humanizeMessage(message, labels);
    expect(out.content.direct_answer).toBe("Subiu.");
    expect(out.content.evidence).toEqual(["Novos clientes ok"]);
    const user = { id: "2", role: "user", content: { question: "metric_ids: orders?" } } as unknown as IntelligenceMessage;
    expect(humanizeMessage(user)).toBe(user);
  });
});
