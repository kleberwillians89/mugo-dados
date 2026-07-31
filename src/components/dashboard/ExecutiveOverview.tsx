type Tone = "positive" | "neutral" | "attention";

export type ExecutiveMetric = {
  key: string;
  label: string;
  value: number | null;
  previous?: number | null;
  format?: "number" | "currency" | "ratio";
  context: string;
  inverse?: boolean;
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

function change(current: number, previous: number): { absolute: number; percent: number | null } {
  const absolute = current - previous;
  return {
    absolute,
    percent: previous === 0 ? null : (absolute / Math.abs(previous)) * 100,
  };
}

function toneFor(metric: ExecutiveMetric): Tone {
  if (metric.value == null || metric.previous == null) return "neutral";
  const direction = metric.value - metric.previous;
  if (direction === 0) return "neutral";
  const positive = metric.inverse ? direction < 0 : direction > 0;
  return positive ? "positive" : "attention";
}

function signed(value: number, digits = 0): string {
  const formatted = Math.abs(value).toLocaleString("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatted}`;
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
  const comparable = metrics.filter(
    (metric): metric is ExecutiveMetric & { value: number; previous: number } =>
      metric.value != null && metric.previous != null
  );
  const ranked = comparable
    .map((metric) => ({ metric, ...change(metric.value, metric.previous) }))
    .filter((item) => item.percent != null)
    .sort((left, right) => Math.abs(right.percent || 0) - Math.abs(left.percent || 0));
  const advance = ranked.find((item) => toneFor(item.metric) === "positive") || null;
  const risk = ranked.find((item) => toneFor(item.metric) === "attention") || null;
  const reach = metrics.find((metric) => metric.key === "reach")?.value ?? null;
  const interactions = metrics.find((metric) => metric.key === "interactions")?.value ?? null;
  const visits = metrics.find((metric) => metric.key === "profile_views")?.value ?? null;
  const clicks = metrics.find((metric) => metric.key === "website_clicks")?.value ?? null;
  const spend = metrics.find((metric) => metric.key === "spend")?.value ?? null;
  const roas = metrics.find((metric) => metric.key === "roas")?.value ?? null;
  const hasAnyData = metrics.some((metric) => metric.value != null);

  const opportunity =
    visits != null && clicks != null
      ? `${visits.toLocaleString("pt-BR")} visitas ao perfil geraram ${clicks.toLocaleString("pt-BR")} cliques no link. Esse é o ponto observável mais próximo da intenção comercial.`
      : reach != null && interactions != null
        ? `${reach.toLocaleString("pt-BR")} contas alcançadas e ${interactions.toLocaleString("pt-BR")} interações formam a base disponível para avaliar conteúdo.`
        : "Conecte e sincronize as fontes para identificar uma oportunidade sustentada por evidência.";

  const nextAction = risk
    ? `Investigar primeiro ${risk.metric.label.toLowerCase()}, que variou ${signed(risk.percent || 0, 1)}% contra o período anterior.`
    : visits != null && clicks != null
      ? "Revisar as publicações que mais geraram visitas e cliques antes de decidir o próximo investimento."
      : "Completar a cobertura das fontes antes de tomar decisões de otimização.";

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

      <div className="executiveStory">
        <div className="executiveStoryLead">
          <span className="executiveEyebrow">Visão do período</span>
          {loading && !hasAnyData ? (
            <div className="executiveSkeleton" aria-label="Carregando visão do período" />
          ) : !hasAnyData ? (
            <h2>Ainda não há dados suficientes para construir uma leitura executiva.</h2>
          ) : (
            <h2>
              {advance
                ? `${advance.metric.label} foi o principal avanço mensurável, com ${signed(advance.percent || 0, 1)}%.`
                : "O período não apresenta avanço comparável confirmado nas métricas disponíveis."}
            </h2>
          )}
          <p>
            {risk
              ? `${risk.metric.label} é o principal ponto de atenção: ${signed(risk.absolute)} em termos absolutos e ${signed(risk.percent || 0, 1)}% ante o período anterior.`
              : "Não há queda comparável confirmada, ou a cobertura ainda não permite essa conclusão."}
          </p>
        </div>
        <div className="executiveStoryNotes">
          <article><span>Maior oportunidade</span><p>{opportunity}</p></article>
          <article><span>Próxima ação</span><p>{nextAction}</p></article>
        </div>
      </div>

      <div className="executiveKpiGrid">
        {metrics.map((metric) => {
          const tone = toneFor(metric);
          const delta =
            metric.value != null && metric.previous != null
              ? change(metric.value, metric.previous)
              : null;
          return (
            <article className={`executiveKpi is-${tone}`} key={metric.key}>
              <div className="executiveKpiHead">
                <span>{metric.label}</span>
                <i aria-label={tone === "positive" ? "Resultado positivo" : tone === "attention" ? "Requer atenção" : "Estado neutro"} />
              </div>
              <strong>{metric.value == null ? "Indisponível" : formatMetric(metric.value, metric.format)}</strong>
              <p>{metric.context}</p>
              <footer>
                {delta ? (
                  <>
                    <b>{delta.percent == null ? "Base anterior zerada" : `${signed(delta.percent, 1)}%`}</b>
                    <span>{signed(delta.absolute)} em valor absoluto</span>
                  </>
                ) : (
                  <span>Sem comparação confiável para este indicador</span>
                )}
              </footer>
            </article>
          );
        })}
      </div>

      <div className="executiveJourney">
        <div>
          <span className="executiveEyebrow">História observável</span>
          <h2>Da atenção à intenção</h2>
          <p>As etapas comerciais aparecem somente quando a fonte correspondente fornece dados confiáveis.</p>
        </div>
        <ol>
          {[
            { label: "Investimento", value: spend, format: "currency" as const, source: "Meta Ads" },
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
          <div><span>Retorno observado</span><strong>{roas == null ? "Indisponível" : formatMetric(roas, "ratio")}</strong></div>
          <p>Receita, pedidos, clientes e produtos não são inferidos neste painel quando a fonte comercial não está presente.</p>
        </div>
      </div>

      <div className="executiveActions">
        <article className={risk ? "isAttention" : ""}>
          <span>{risk ? "Atenção" : "Informação"}</span>
          <h3>{risk ? `Revisar ${risk.metric.label}` : "Comparação ainda limitada"}</h3>
          <p>{risk ? nextAction : "Aguarde uma cobertura comparável antes de interpretar variações."}</p>
          <small>Fonte: dados consolidados do período</small>
        </article>
        <article>
          <span>Oportunidade</span>
          <h3>Conectar alcance à intenção</h3>
          <p>{opportunity}</p>
          <small>Fonte: Instagram Graph</small>
        </article>
        <article>
          <span>Prioridade seguinte</span>
          <h3>Completar a visão comercial</h3>
          <p>Use as fontes de vendas conectadas para confirmar faturamento, pedidos, clientes e produtos sem estimativas.</p>
          <small>Impacto esperado: melhor qualidade de decisão</small>
        </article>
      </div>
    </section>
  );
}
