import type { AiAction } from "../app/aiActions";

export const AI_ACTIONS_FIXTURE: AiAction[] = [
  { id: "a1", kind: "campanha_reativacao", status: "proposta", proposed_at: "2026-11-12T11:41:00Z", decided_at: null, executed_at: null, error: null, result: {},
    title: "Reativar 340 clientes que pararam de comprar",
    rationale: "340 clientes que aceitaram receber e-mails não compram há mais de 90 dias. O ticket médio deles é R$ 238; trazer 5% de volta paga a campanha várias vezes, sem custo de mídia.",
    evidence: { inactive_with_consent: 340, days: 90, avg_ticket: 238.4 },
    payload: { subject: "{{primeiro_nome}}, a coleção de verão chegou", text: "Faz um tempo que você não passa por aqui. Tem legging nova, top novo e as cores que você pediu." } },
  { id: "a2", kind: "ligar_fluxo", status: "proposta", proposed_at: "2026-11-12T11:41:00Z", decided_at: null, executed_at: null, error: null, result: {},
    title: "Ligar o fluxo de segunda compra no dia 41",
    rationale: "Só 22,5% dos clientes compraram de novo, e quem volta costuma voltar perto do dia 41. Um e-mail automático nesse momento ajuda a puxar a segunda compra.",
    evidence: { repeat_rate: 22.5, customers: 6083, median_days_to_second: 41 }, payload: { flow: "segunda_compra", delay_days: 41 } },
  { id: "a3", kind: "alerta_cac", status: "proposta", proposed_at: "2026-11-12T11:41:00Z", decided_at: null, executed_at: null, error: null, result: {},
    title: "CAC subiu 35,7% em outubro",
    rationale: "O custo para trazer um cliente novo foi R$ 95, contra R$ 70 de média nos meses anteriores. O gasto subiu mais rápido que os clientes novos.",
    evidence: { cac_last_month: 95, cac_avg_prev: 70, increase_pct: 35.7 }, payload: {} },
  { id: "a4", kind: "ligar_carrinho", status: "executada", proposed_at: "2026-11-03T11:41:00Z", decided_at: "2026-11-03T14:10:00Z", executed_at: "2026-11-03T14:10:00Z",
    error: null, result: {}, title: "Ligar a recuperação de carrinho por e-mail", rationale: "", evidence: {}, payload: {},
    measurement: { sent: 168, buyers: 31, revenue: 9874.3 } },
];
