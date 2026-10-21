import type { IntelligenceAnalysisRecord } from "../../app/intelligenceTypes";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { generateIntelligenceAnalysis, getLatestIntelligenceAnalysis } from "../../app/api";
import { getActiveClientId } from "../../app/activeClient";
import { selectMovements } from "../../app/intelligencePriority";
import {
  comparableReportMetric, formatMetric, printIntelligenceReport, reportDate, reportPeriod,
  sourceLabel, validReport, type IntelligenceReport, type ReportKind,
} from "../../app/intelligenceReport";
import reportStyles from "../../styles/intelligence-reports.css?raw";
import "../../styles/intelligence-reports.css";

const SOURCE_STATUS: Record<string, string> = {
  available: "Disponível", partial: "Cobertura parcial", no_data: "Sem dados",
  connected_no_data: "Conectada, sem dados", disconnected: "Desconectada", error: "Falha na leitura",
};
const PRIORITIES = ["now", "week", "monitor", "investigate"];
const PRIORITY_LABELS = { now: "Fazer agora", week: "Nesta semana", monitor: "Acompanhar", investigate: "Investigar" };
const CATEGORIES = { positive: "Fato observado", opportunity: "Oportunidade", risk: "Risco", attention: "Atenção", anomaly: "Anomalia", data_quality: "Qualidade dos dados" };

export function IntelligenceReportDocument({ report }: { report: IntelligenceReport }) {
  const record = report.analysis, content = record.analysis!;
  const metrics = new Map(record.metrics_snapshot.map(metric => [metric.id, metric]));
  const supported = (id: string) => {
    const metric = metrics.get(id);
    return metric?.value != null && ["confirmed", "partial"].includes(metric.status);
  };
  const insights = selectMovements(content.insights.filter(item => item.metric_ids.some(supported)), metrics);
  const actions = content.actions.filter(action => action.recommendation.trim() && supported(action.metric_id))
    .sort((a, b) => PRIORITIES.indexOf(a.priority) - PRIORITIES.indexOf(b.priority)).slice(0, 3);
  const channels = [...new Set(record.metrics_snapshot.map(metric => metric.source))];
  return <article className="mugoReport" aria-label="Prévia do relatório">
    <header className="mugoReportHeader">
      <strong className="mugoReportBrand">Mugô<span>Dados & decisões</span></strong>
      <p>Relatório {report.kind === "weekly" ? "Semanal" : "Mensal"}</p>
      <h2>{report.companyName}</h2>
      <p>{reportDate(record.period_start)} — {reportDate(record.period_end)}</p>
      <small>Análise de {reportDate(record.completed_at || record.created_at)} · Horário de São Paulo</small>
    </header>
    <section className="mugoReportExecutive"><h3>Resumo executivo</h3><p>{content.executive.overall}</p></section>
    <section><h3>Fontes, cobertura e limitações</h3>
      <p role="status">{record.data_quality.message || "Cobertura temporal não informada na análise salva."}</p>
      {record.data_quality.status !== "good" ? <p className="mugoReportWarning">Relatório com dados parciais ou limitados. As lacunas não representam zero.</p> : null}
      <ul>{record.sources.map(source => <li key={source.id}><strong>{source.label}</strong> — {SOURCE_STATUS[source.status] || "Cobertura não informada"}.
        {source.covered_days == null ? " Sem cobertura temporal confirmada." : ` ${source.covered_days} dias com dados no período.`}</li>)}</ul>
      {!record.sources.length ? <p>As fontes não foram detalhadas na análise salva.</p> : null}
    </section>
    <section><h3>Indicadores canônicos</h3><div className="mugoReportKpis">{record.metrics_snapshot.map(metric => <div key={metric.id}>
      <span>{metric.label}</span><strong>{formatMetric(metric)}</strong><small>{sourceLabel(metric.source)} · {metric.status === "confirmed" ? "Confirmado" : metric.status === "partial" ? "Parcial" : "Sem evidência disponível"}</small>
      {comparableReportMetric(metric) ? <small>{metric.variation_percent! > 0 ? "+" : ""}{metric.variation_percent!.toLocaleString("pt-BR")}% vs. período anterior</small> : <small>Sem comparação validada disponível.</small>}
    </div>)}</div>{!record.metrics_snapshot.length ? <p>Não há indicadores no snapshot desta análise.</p> : null}
      <p className="mugoReportNote">Variações somente quando fornecidas pela Inteligência para indicadores confirmados, com base anterior disponível. Nenhuma comparação é calculada neste relatório.</p>
    </section>
    <section><h3>Oportunidades e riscos</h3>{insights.length ? insights.map((insight, index) => <div className="mugoReportInsight" key={`${insight.title}-${index}`}>
      <small>{CATEGORIES[insight.category]} · confiança {({ high: "alta", medium: "média", low: "baixa" })[insight.confidence]}</small><h4>{insight.title}</h4>
      <p><strong>Evidência: </strong>{insight.metric_ids.filter(supported).map(id => `${metrics.get(id)!.label}: ${formatMetric(metrics.get(id)!)}`).join(" · ")}</p>
      <p><strong>Interpretação: </strong>{insight.interpretation}</p><p><strong>Ação recomendada: </strong>{insight.action}</p>
    </div>) : <p>Não há insights sustentados suficientes nesta análise.</p>}</section>
    <section><h3>Leitura por canal</h3>{channels.map(channel => <div className="mugoReportChannel" key={channel}>
      <h4>{sourceLabel(channel)}</h4><ul>{record.metrics_snapshot.filter(metric => metric.source === channel).map(metric => <li key={metric.id}>{metric.label}: {formatMetric(metric)}</li>)}</ul>
      {content.insights.filter(insight => insight.metric_ids.some(id => supported(id) && metrics.get(id)?.source === channel)).map((insight, index) => <p key={index}>{insight.title} — {insight.interpretation}</p>)}
    </div>)}<p className="mugoReportNote">Valores por origem, sem somar atribuições de canais nem criar relações causais.</p></section>
    <section><h3>Ações prioritárias</h3>{actions.length ? <ol>{actions.map((action, index) => <li className="mugoReportAction" key={index}>
      <small>{PRIORITY_LABELS[action.priority]}</small><h4>{action.recommendation}</h4><p>{action.justification}</p>
      <p>Evidência: {metrics.get(action.metric_id)!.label}: {formatMetric(metrics.get(action.metric_id)!)}</p>
      {action.impact_expected ? <p>Impacto esperado (hipótese): {action.impact_expected}</p> : null}
    </li>)}</ol> : <p>Não há ações prioritárias com evidências suficientes. Nenhuma ação foi inventada para completar a lista.</p>}</section>
    <footer>Mugô Dados · Relatório baseado na análise validada e nos dados persistidos da empresa. Recomendações são hipóteses, não garantias de resultado.</footer>
  </article>;
}

type Props = { clientId: string; clientName: string; initialDate: string; providerConfigured: boolean | null };
export default function IntelligenceReports({ clientId, clientName, initialDate, providerConfigured }: Props) {
  const [kind, setKind] = useState<ReportKind>("monthly");
  const [reference, setReference] = useState(initialDate);
  const [report, setReport] = useState<IntelligenceReport | null>(null);
  const [pending, setPending] = useState<"generate" | "read" | null>(null);
  const [error, setError] = useState("");
  const [empty, setEmpty] = useState(false);
  const request = useRef<AbortController | null>(null);
  const preview = useRef<HTMLDivElement>(null);
  useEffect(() => () => { request.current?.abort(); }, []);
  let selectedPeriod: ReturnType<typeof reportPeriod> | undefined;
  try { selectedPeriod = reportPeriod(kind, reference); } catch { /* Invalid date disables submission. */ }
  const shown = report?.analysis.client_id === clientId && getActiveClientId() === clientId ? report : null;

  async function load(mode: "generate" | "read") {
    if (!clientId || request.current || !selectedPeriod || getActiveClientId() !== clientId || (mode === "generate" && providerConfigured === false)) return;
    const controller = new AbortController(); request.current = controller;
    const period = selectedPeriod, requestedKind = kind;
    setPending(mode); setError(""); setEmpty(false);
    try {
      let analysis: IntelligenceAnalysisRecord | null, companyName = clientName;
      if (mode === "generate") {
        const response = await generateIntelligenceAnalysis(period, { signal: controller.signal });
        if (controller.signal.aborted || getActiveClientId() !== clientId) return;
        if (response.snapshot.client.id !== clientId) throw new Error("REPORT_NOT_VALIDATED");
        analysis = response.analysis; companyName = response.snapshot.client.name;
      } else {
        const response = await getLatestIntelligenceAnalysis(period, { signal: controller.signal });
        if (controller.signal.aborted || getActiveClientId() !== clientId) return;
        analysis = response.analysis;
        if (!analysis) { setEmpty(true); return; }
      }
      if (!validReport(analysis, clientId, period)) throw new Error("REPORT_NOT_VALIDATED");
      setReport({ kind: requestedKind, companyName, analysis });
    } catch (failure) {
      if (!controller.signal.aborted && getActiveClientId() === clientId) {
        const message = failure instanceof Error ? failure.message : "";
        setError(/AI_INSUFFICIENT_DATA|dados suficientes/i.test(message)
          ? "Ainda não há dados suficientes para gerar um relatório confiável neste período. O relatório anterior, se houver, foi preservado."
          : "Não foi possível obter um relatório validado agora. O relatório anterior, se houver, foi preservado. Tente novamente mais tarde.");
      }
    } finally {
      if (request.current === controller) { request.current = null; setPending(null); }
    }
  }
  function submit(event: FormEvent) { event.preventDefault(); void load("generate"); }
  function exportPdf() {
    if (!shown || !preview.current || getActiveClientId() !== clientId) return;
    try { printIntelligenceReport(preview.current, `Mugô — ${shown.kind === "weekly" ? "Semanal" : "Mensal"} — ${shown.companyName} — ${shown.analysis.period_start} a ${shown.analysis.period_end}`, reportStyles); }
    catch { setError("Não foi possível abrir a impressão. Permita a janela e selecione Salvar como PDF no navegador."); }
  }
  return <section className="intelSection mugoReportsWorkspace" aria-label="Relatórios com IA">
    <div className="intelSectionTitle"><div><span className="intelEyebrow">Relatórios com IA</span><h2>Da leitura à decisão recorrente</h2></div></div>
    <p>Empresa: <strong>{clientName}</strong>. Para trocar, use o seletor de empresa da navegação.</p>
    <form onSubmit={submit} className="mugoReportControls">
      <label>Periodicidade<select value={kind} disabled={!!pending} onChange={event => { setKind(event.target.value as ReportKind); setEmpty(false); }}><option value="weekly">Relatório Semanal</option><option value="monthly">Relatório Mensal</option></select></label>
      <label>Data de referência<input type="date" value={reference} disabled={!!pending} onChange={event => { setReference(event.target.value); setEmpty(false); }} required /></label>
      <p>{selectedPeriod ? `${reportDate(selectedPeriod.start)} — ${reportDate(selectedPeriod.end)}` : "Selecione uma data válida."}<small>Semana de segunda a domingo ou mês calendário completo.</small></p>
      <button className="btn btnPrimary" disabled={!!pending || !selectedPeriod || providerConfigured === false}>{pending === "generate" ? "Gerando relatório…" : "Gerar relatório com IA"}</button>
      <button type="button" className="btn" disabled={!!pending || !selectedPeriod} onClick={() => void load("read")}>{pending === "read" ? "Carregando…" : "Ver análise salva deste período"}</button>
    </form>
    <p className="intelSourcesNote">Gerar usa o pipeline existente de IA e pode ter custo. Nada é gerado automaticamente. Exportar ou carregar uma análise salva não chama a IA.</p>
    {providerConfigured === false ? <p role="status">A geração está indisponível. Você ainda pode consultar uma análise salva.</p> : null}
    {pending ? <p role="status">{pending === "generate" ? "Gerando a análise e validando as evidências…" : "Consultando a análise salva…"}</p> : null}
    {error ? <p role="alert" className="intelInlineWarning">{error}</p> : null}
    {empty ? <p role="status">Não há análise válida salva para o período selecionado.{shown ? " A prévia anterior permanece abaixo, com seu período identificado." : ""}</p> : null}
    {!shown && !pending && !error && !empty ? <p className="intelEmpty">Escolha um período para gerar ou consultar um relatório. Nenhum conteúdo será inventado na ausência de dados.</p> : null}
    {shown ? <><div className="mugoReportExport"><p>Relatório exibido: {reportDate(shown.analysis.period_start)} — {reportDate(shown.analysis.period_end)}</p><button type="button" className="btn" onClick={exportPdf}>Exportar PDF</button><small>Na janela de impressão, selecione Salvar como PDF.</small></div><div ref={preview}><IntelligenceReportDocument report={shown} /></div></> : null}
  </section>;
}
