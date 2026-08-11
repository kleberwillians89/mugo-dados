import { changeOf, computeExecutiveNarrative, signedValue } from "./executiveNarrative";

export type ExecutiveMetric = {
  key: string;
  label: string;
  value: number | null;
  previous?: number | null;
  format?: "number" | "currency" | "ratio";
  context: string;
  inverse?: boolean;
  source?: string;
};

export type ExecutiveSource = {
  label: string;
  state: "connected" | "waiting" | "error";
  detail: string;
};

type Props = {
  companyName: string;
  commercePlatform?: string | null;
  periodLabel: string;
  comparisonLabel: string;
  updatedLabel: string;
  partialCoverage?: string | null;
  metrics: ExecutiveMetric[];
  sources: ExecutiveSource[];
  loading?: boolean;
  error?: string | null;
};

function formatMetric(value: number, format: ExecutiveMetric["format"]): string {
  if (format === "currency") {
    return value.toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
      maximumFractionDigits: 2,
    });
  }
  if (format === "ratio") return `${value.toFixed(2)}x`;
  return value.toLocaleString("pt-BR");
}

function compactCurrency(value: number): string {
  if (Math.abs(value) >= 1000) {
    return `R$ ${(value / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil`;
  }
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
}

export default function ExecutiveOverview({
  companyName,
  commercePlatform,
  periodLabel,
  comparisonLabel,
  updatedLabel,
  partialCoverage,
  metrics,
  sources,
  loading = false,
  error = null,
}: Props) {
  const narrative = computeExecutiveNarrative(metrics);
  const { advance } = narrative;
  const reach = metrics.find((metric) => metric.key === "reach")?.value ?? null;
  const interactions = metrics.find((metric) => metric.key === "interactions")?.value ?? null;
  const visits = metrics.find((metric) => metric.key === "profile_views")?.value ?? null;
  const clicks = metrics.find((metric) => metric.key === "website_clicks")?.value ?? null;
  const spend = metrics.find((metric) => metric.key === "spend");
  const roas = metrics.find((metric) => metric.key === "roas");
  const revenue = metrics.find((metric) => metric.key === "revenue");
  const conversions = metrics.find((metric) => metric.key === "conversions");
  const hasAnyData = metrics.some((metric) => metric.value != null);
  const hasMediaPerformance = revenue?.value != null;
  const revenueDelta =
    revenue?.value != null && revenue?.previous != null ? changeOf(revenue.value, revenue.previous) : null;
  const periodImpact = metrics.flatMap((metric) => {
    if (metric.value == null || metric.previous == null) return [];
    const change = changeOf(metric.value, metric.previous);
    if (change.absolute === 0) return [];
    return [{ metric, change }];
  }).slice(0, 4);

  return (
    <section className="executiveOverview" aria-labelledby="executive-title">
      <header className="executiveHero">
        <div>
          <span className="executiveEyebrow">Leitura executiva</span>
          <h1 id="executive-title">{companyName}</h1>
          <p>
            {commercePlatform ? `${commercePlatform} conectado` : "E-commerce não conectado"}
            {" · "}Uma leitura do que aconteceu e do que merece atenção.
          </p>
        </div>
        <dl className="executiveContext">
          <div><dt>Período</dt><dd>{periodLabel}</dd></div>
          <div><dt>Comparação</dt><dd>{comparisonLabel}</dd></div>
          <div><dt>Atualização</dt><dd>{updatedLabel}</dd></div>
        </dl>
      </header>

      <div className="executiveSourceRow" aria-label="Estado das fontes">
        {sources.map((source) => (
          <div className={`executiveSource is-${source.state}`} key={source.label}>
            <span aria-hidden="true" />
            <div><strong>{source.label}</strong><small>{source.detail}</small></div>
          </div>
        ))}
      </div>

      {partialCoverage ? <div className="executiveNotice">{partialCoverage}</div> : null}
      {error ? <div className="executiveNotice isError">Parte das fontes não respondeu. A última leitura válida foi preservada.</div> : null}

      {periodImpact.length ? (
        <section className="executiveImpact" aria-labelledby="impact-title">
          <div><span className="executiveEyebrow">Impacto do período</span><h2 id="impact-title">O que mudou</h2></div>
          <div className="executiveImpactGrid">
            {periodImpact.map(({ metric, change }) => (
              <article key={metric.key}>
                <strong>
                  {metric.key === "followers"
                    ? signedValue(metric.value || 0)
                    : change.percent == null
                    ? signedValue(change.absolute, metric.format === "ratio" ? 2 : 0)
                    : `${signedValue(change.percent, 1)}%`}
                </strong>
                <span>{metric.label}</span>
                <small>{metric.key === "followers" ? "no período acompanhado" : change.percent == null ? "Variação absoluta" : "vs. período anterior"}</small>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {/* Composição única de performance: nunca vários cards concorrendo —
          um resultado central (receita atribuída Meta), com investimento,
          ROAS e compras como apoio do mesmo parágrafo visual. */}
      {loading && !hasAnyData ? (
        <div className="performanceHero">
          <div className="executiveSkeleton" aria-label="Carregando performance" />
        </div>
      ) : hasMediaPerformance && revenue?.value != null ? (
        <div className="performanceHero">
          <span className="executiveEyebrow">Performance de mídia paga</span>
          <p className="performanceNarrative">
            {revenueDelta && revenueDelta.percent != null
              ? revenueDelta.percent >= 0
                ? "A receita atribuída pela Meta continua crescendo."
                : "A receita atribuída pela Meta recuou neste período."
              : "A receita atribuída pela Meta no período selecionado."}
          </p>
          <div className="performanceMain">
            <strong>{compactCurrency(revenue.value)}</strong>
            <span className="performanceMainLabel">Receita atribuída Meta</span>
          </div>
          {revenueDelta && revenueDelta.percent != null ? (
            <span className={`performanceDelta ${revenueDelta.percent >= 0 ? "is-up" : "is-down"}`}>
              {revenueDelta.percent >= 0 ? "↑" : "↓"} {signedValue(revenueDelta.percent, 1)}% vs. período anterior
            </span>
          ) : (
            <span className="performanceDelta is-neutral">Sem base comparável no período anterior</span>
          )}
          <div className="performanceSub">
            {spend ? (
              <div><span>Investimento</span><b>{spend.value != null ? formatMetric(spend.value, "currency") : "Sem dados"}</b></div>
            ) : null}
            {roas ? (
              <div><span>ROAS</span><b>{roas.value != null ? formatMetric(roas.value, "ratio") : "Sem dados"}</b></div>
            ) : null}
            {conversions ? (
              <div><span>Compras</span><b>{conversions.value != null ? formatMetric(conversions.value, "number") : "Sem dados"}</b></div>
            ) : null}
          </div>
          <span className="performanceSource">Fonte: Meta Ads</span>
        </div>
      ) : !hasAnyData ? (
        <div className="performanceHero is-empty">
          <span className="executiveEyebrow">Performance</span>
          <p className="performanceNarrative">Ainda não há dados suficientes para construir uma leitura executiva.</p>
        </div>
      ) : (
        <div className="performanceHero is-empty">
          <span className="executiveEyebrow">Performance de mídia paga</span>
          <p className="performanceNarrative">
            {advance
              ? `${advance.metric.label} foi o principal avanço mensurável, com ${signedValue(advance.percent || 0, 1)}%.`
              : "Conecte o Meta Ads para acompanhar receita, investimento e ROAS aqui."}
          </p>
        </div>
      )}

      <div className="executiveJourney">
        <div>
          <span className="executiveEyebrow">História observável</span>
          <h2>Da atenção à intenção</h2>
          <p>As etapas comerciais aparecem somente quando a fonte correspondente fornece dados confiáveis.</p>
        </div>
        <ol>
          {[
            { label: "Investimento", value: spend?.value ?? null, format: "currency" as const, source: "Meta Ads" },
            { label: "Alcance", value: reach, format: "number" as const, source: "Instagram" },
            { label: "Interações", value: interactions, format: "number" as const, source: "Instagram" },
            { label: "Visitas", value: visits, format: "number" as const, source: "Instagram" },
            { label: "Cliques", value: clicks, format: "number" as const, source: "Instagram" },
          ].filter((step) => step.value != null).map((step, index) => (
            <li key={step.label}>
              <span>{index + 1}</span>
              <div><small>{step.label}</small><strong>{formatMetric(step.value!, step.format)}</strong><em>{step.source}</em></div>
            </li>
          ))}
        </ol>
        <div className="executiveCommerceGap">
          <div><span>Retorno observado</span><strong>{roas?.value == null ? "Sem dados" : formatMetric(roas.value, "ratio")}</strong></div>
          <p>Receita, pedidos, clientes e produtos não são inferidos neste painel quando a fonte comercial não está presente.</p>
        </div>
      </div>

      {hasAnyData ? (
        <section className="executiveReading" aria-labelledby="reading-title">
          <div>
            <span className="executiveEyebrow">Leitura Mugô</span>
            <h2 id="reading-title">Da evidência ao próximo movimento</h2>
          </div>
          <div className="executiveReadingGrid">
            <article><span>O que aconteceu</span><p>{advance ? `${advance.metric.label} avançou ${signedValue(advance.percent || 0, 1)}% no comparativo.` : "O período ainda não tem avanço comparável suficiente."}</p></article>
            <article><span>Por que importa</span><p>{narrative.opportunity}</p></article>
            <article><span>Próxima ação</span><p>{narrative.nextAction}</p><small>Prioridade baseada nos dados disponíveis</small></article>
          </div>
        </section>
      ) : null}
    </section>
  );
}
