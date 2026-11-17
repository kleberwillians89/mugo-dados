import {
  CHANNELS,
  money,
  num,
  percent,
  ratio,
  type CampaignAction,
  type Objective,
  type Strategy,
  type SavedStrategy,
} from "./media";

export type SimpleMediaMetric = { label: string; value: string; explanation?: string };
export type SimpleMediaCampaign = {
  campaign: string;
  channel: string;
  facts: string[];
  decisionReason: string;
  explanation: string | null;
};
export type SimpleMediaView = {
  summary: string;
  period: string;
  metrics: SimpleMediaMetric[];
  wins: SimpleMediaCampaign[];
  improvements: SimpleMediaCampaign[];
  recommendations: string[];
  winsLimitation: string | null;
  dataLimitation: string | null;
};

const observedCampaign = (row: CampaignAction, objective: Objective): SimpleMediaCampaign => {
  const facts = [`${money(row.spend)} investidos nos últimos 30 dias`];
  if (objective === "vendas") {
    facts.push(`${money(row.revenue)} de receita atribuída`, `ROAS ${ratio(row.roas)}`);
  } else {
    facts.push(`${num(row.conversions)} conversões registradas`, `CPA ${money(row.cpa)}`);
  }
  return {
    campaign: row.campaign,
    channel: CHANNELS[row.channel],
    facts,
    decisionReason: row.why,
    explanation: row.learning || null,
  };
};

function rankedWins(campaigns: CampaignAction[], objective: Objective, metric: Strategy["metric"]): CampaignAction[] {
  const eligible = campaigns.filter((row) => !row.suggested && !row.boost && row.spend > 0 && (row.action === "escalar" || row.action === "manter"));
  if (objective === "vendas" && metric === "revenue") {
    return eligible.filter((row) => row.revenue > 0).sort((a, b) => b.revenue - a.revenue || (b.roas || 0) - (a.roas || 0)).slice(0, 3);
  }
  if ((objective === "leads" || objective === "remarketing") && metric === "conversions") {
    return eligible.filter((row) => row.conversions > 0).sort((a, b) => b.conversions - a.conversions || (a.cpa ?? Infinity) - (b.cpa ?? Infinity)).slice(0, 3);
  }
  return [];
}

function limitationForObjective(objective: Objective, hasCampaigns: boolean): string | null {
  if (!hasCampaigns) return "Não há campanhas com dados suficientes para comparar neste período.";
  if (objective === "trafego") return "Os dados atuais não trazem cliques por campanha nesta análise. Por isso, não é seguro apontar as melhores campanhas de tráfego.";
  if (objective === "alcance") return "Os dados atuais não trazem impressões ou alcance único por campanha nesta análise. Impressões também não equivalem a pessoas únicas.";
  if (objective === "retencao") return "Receita atribuída e conversões de mídia não comprovam retenção. É necessário um indicador de recompra ou permanência por campanha.";
  return null;
}

export function buildSimpleMediaView(strategy: Strategy | SavedStrategy, campaigns: CampaignAction[]): SimpleMediaView {
  const diagnosis = strategy.diagnosis.filter((item) => item.confidence === "boa" || item.confidence === "baixa");
  const observed = diagnosis.reduce((total, item) => ({
    spend: total.spend + item.recent.spend,
    revenue: total.revenue + item.recent.revenue,
    conversions: total.conversions + item.recent.conversions,
    clicks: total.clicks + item.recent.clicks,
    impressions: total.impressions + item.recent.impressions,
  }), { spend: 0, revenue: 0, conversions: 0, clicks: 0, impressions: 0 });
  const roas = observed.spend ? observed.revenue / observed.spend : null;
  const cpa = observed.conversions ? observed.spend / observed.conversions : null;
  const cpc = observed.clicks ? observed.spend / observed.clicks : null;
  const ctr = observed.impressions ? observed.clicks / observed.impressions : null;
  const hasObservedData = observed.spend > 0 || observed.clicks > 0 || observed.impressions > 0 || observed.conversions > 0;

  const metrics: SimpleMediaMetric[] = [{ label: "Investimento em mídia paga", value: money(observed.spend) }];
  if (strategy.objective === "vendas") {
    metrics.push({ label: "Receita atribuída", value: money(observed.revenue), explanation: "Receita associada aos anúncios; não representa toda a receita da empresa." });
    metrics.push({ label: "ROAS", value: ratio(roas), explanation: "Quanto voltou em receita atribuída para cada R$ 1 investido." });
  } else if (strategy.objective === "trafego") {
    metrics.push({ label: "Cliques nos anúncios", value: num(observed.clicks), explanation: "Clique não equivale necessariamente a uma visita concluída ao site." });
    metrics.push({ label: "CPC", value: money(cpc), explanation: "Custo médio por clique no anúncio." });
  } else if (strategy.objective === "alcance") {
    metrics.push({ label: "Impressões", value: num(observed.impressions), explanation: "Número de exibições; não equivale ao alcance de pessoas únicas." });
    metrics.push({ label: "CTR", value: percent(ctr, 2), explanation: "Percentual de exibições que geraram clique." });
  } else {
    metrics.push({ label: "Conversões registradas", value: num(observed.conversions), explanation: strategy.objective === "leads"
      ? "Conversão é o evento configurado na plataforma e não comprova, sozinha, um lead qualificado."
      : strategy.objective === "retencao"
        ? "Conversões e receita atribuída não comprovam retenção de clientes."
        : "Conversão é o evento configurado; confirme se ele corresponde ao remarketing analisado." });
    metrics.push({ label: "CPA", value: money(cpa), explanation: "Custo médio por conversão registrada." });
  }

  const wins = rankedWins(campaigns, strategy.objective, strategy.metric).map((row) => observedCampaign(row, strategy.objective));
  const improvements = campaigns
    .filter((row) => !row.suggested && !row.boost && row.spend > 0 && (row.action === "pausar" || row.action === "otimizar"))
    .sort((a, b) => b.spend - a.spend)
    .slice(0, 3)
    .map((row) => observedCampaign(row, strategy.objective));
  const recommendations = (strategy.narrative?.next_7_days || []).filter(Boolean).slice(0, 3);
  const resultSummary = strategy.objective === "vendas"
    ? `${money(observed.revenue)} de receita atribuída`
    : strategy.objective === "trafego"
      ? `${num(observed.clicks)} cliques nos anúncios`
      : strategy.objective === "alcance"
        ? `${num(observed.impressions)} impressões`
        : `${num(observed.conversions)} conversões registradas`;

  return {
    summary: hasObservedData
      ? `Nos últimos 30 dias, a mídia paga investiu ${money(observed.spend)} e registrou ${resultSummary}.`
      : "Ainda não há dados observados suficientes para resumir o desempenho deste período.",
    period: `${strategy.window.start} a ${strategy.window.end}`,
    metrics,
    wins,
    improvements,
    recommendations,
    winsLimitation: wins.length ? null : limitationForObjective(strategy.objective, campaigns.some((row) => !row.suggested && !row.boost && row.spend > 0)),
    dataLimitation: hasObservedData ? null : "O Resumo Executivo não substitui dados ausentes por estimativas nem mistura desempenho orgânico com mídia paga.",
  };
}
