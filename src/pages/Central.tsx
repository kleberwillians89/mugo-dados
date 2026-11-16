import { useCallback, useEffect, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { STAGES, STUDIO_FORMATS, getCentral, localParts, type CentralView } from "../app/studio";
import { getPathForRoute, navigateToAppRoute, type AppRoute } from "../app/routes";
import { formatCurrency, formatInteger } from "../app/dataFormat";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import AiUsageButton from "../components/studio/AiUsageButton";
import KpiFigure from "../components/data/KpiFigure";
import HealthIndexCard from "../components/clipping/HealthIndexCard";
import HomeChannels from "../components/home/HomeChannels";
import PageSkeleton from "../components/data/PageSkeleton";
import "../styles/studio.css";

const MONTH_NAMES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const thisMonth = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const shiftMonth = (m: string, n: number) => { const d = new Date(Number(m.slice(0, 4)), Number(m.slice(5)) - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const MODULE_ROUTE: Record<string, AppRoute> = { approval: "calendar", calendar: "calendar", media: "media", clipping: "clipping", campaigns: "campaigns", tasks: "tasks" };
const SENT: Record<string, string> = { positivo: "Positiva", neutro: "Neutra", negativo: "Negativa" };

type DashboardSummary = {
  inProgress: number | null;
  waitingApproval: number | null;
  overdue: number | null;
  completed: number | null;
  onTime: number | null;
};

/** Só transforma contagens já existentes; ausência de dado nunca vira zero. */
export function buildDashboardSummary(view: CentralView | null): DashboardSummary {
  const tasksAvailable = Boolean(view?.tasks?.available);
  const counts = view?.calendar?.counts;
  return {
    inProgress: tasksAvailable && typeof view?.tasks?.open === "number" ? view.tasks.open : null,
    waitingApproval: counts ? (counts.revisao_interna ?? 0) + (counts.com_cliente ?? 0) : null,
    overdue: tasksAvailable && typeof view?.tasks?.late === "number" ? view.tasks.late : null,
    // O contrato atual da Central não fornece concluídas nem cumprimento de prazo.
    completed: null,
    onTime: null,
  };
}

export function isCurrentClientRequest(requestClientId: string | null, currentClientId: string | null) {
  return Boolean(requestClientId && requestClientId === currentClientId);
}

function Card({ title, route, children, empty }: { title: string; route: AppRoute; children: React.ReactNode; empty?: string | null }) {
  return <section className="centralCard" aria-label={title}>
    <header><h2>{title}</h2><button type="button" className="studioLink centralOpen" onClick={() => navigateToAppRoute(route)}>Abrir ›</button></header>
    {empty ? <p className="libHint">{empty}</p> : children}
  </section>;
}

function SummaryCard({ label, value, suffix, hint }: { label: string; value: number | null; suffix?: string; hint?: string }) {
  return <article className="centralSummaryCard">
    <span>{label}</span>
    <strong>{value == null ? "—" : `${formatInteger(value)}${suffix || ""}`}</strong>
    <small>{value == null ? "Dado não disponível nesta visão" : hint}</small>
  </article>;
}

/** Dashboard gerencial: prioridades, andamento e resultados usando somente dados já autorizados da Central. */
export default function Central({ isAgency = false }: { isAgency?: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const [month, setMonth] = useState(thisMonth);
  const [view, setView] = useState<CentralView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const requestClientId = getActiveClientId();
    setLoading(true); setError(null);
    try {
      const data = await getCentral(month);
      if (!isCurrentClientRequest(requestClientId, getActiveClientId())) return;
      setView(data);
    } catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível carregar o Dashboard."); }
    finally { setLoading(false); }
  }, [month, clientId]);
  useEffect(() => { void load(); }, [load]);

  const n = view?.numbers;
  const cal = view?.calendar;
  const media = view?.media;
  const clip = view?.clipping;
  const tasks = view?.tasks;
  const summary = buildDashboardSummary(view);

  const today = new Date().toISOString().slice(0, 10);
  const healthStart = `${month}-01`;
  const monthEnd = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5)), 0)).toISOString().slice(0, 10);
  const healthEnd = monthEnd < today ? monthEnd : today;
  return <Shell title="Dashboard" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Dashboard" controls={<div className="calNav">
      <button type="button" className="ds-button" aria-label="Mês anterior" onClick={() => setMonth(shiftMonth(month, -1))}>‹</button>
      <h2 className="calRange">{MONTH_NAMES[Number(month.slice(5)) - 1]} {month.slice(0, 4)}</h2>
      <button type="button" className="ds-button" aria-label="Próximo mês" onClick={() => setMonth(shiftMonth(month, 1))}>›</button>
      <AiUsageButton clientName={clientName} isAgency={isAgency} />
    </div>} />
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {loading && !view ? <PageSkeleton label="Montando o Dashboard com os dados disponíveis…" /> : null}

    {view ? <>
      <section className="centralSummary" aria-label="Resumo gerencial">
        <SummaryCard label="Trabalhos em andamento" value={summary.inProgress} hint="tarefas abertas" />
        <SummaryCard label="Aguardando aprovação" value={summary.waitingApproval} hint="revisão interna ou com o cliente" />
        <SummaryCard label="Tarefas atrasadas" value={summary.overdue} hint="prazos vencidos" />
        <SummaryCard label="Trabalhos concluídos" value={summary.completed} />
        <SummaryCard label="Entregas no prazo" value={summary.onTime} suffix="%" />
      </section>

      <section className="homeHealth centralHealth" aria-label="Saúde da Marca">
        <div className="homeHealthHead"><h2>Saúde da Marca</h2><a href={getPathForRoute("brand_health")}>Abrir análise completa</a></div>
        {healthStart <= today ? <HealthIndexCard start={healthStart} end={healthEnd} compact /> : <p className="studioOk">Este mês ainda não começou.</p>}
      </section>

      {view.alerts.length ? <section className="centralAlerts" aria-label="O que precisa de atenção">
        <h2>O que precisa de atenção</h2>
        <ul>{view.alerts.map((a) => <li key={`${a.module}:${a.text}`} className={`is-${a.level}`}>
          <span>{a.text}</span>{MODULE_ROUTE[a.module] ? <button type="button" className="studioLink" onClick={() => navigateToAppRoute(MODULE_ROUTE[a.module])}>Ver</button> : null}
        </li>)}</ul>
      </section> : <p className="studioOk">Nada pedindo atenção agora.</p>}

      <div className="centralManagementGrid">
        <section className="centralCard" aria-label="Fluxo de trabalho">
          <header><h2>Fluxo de trabalho</h2><button type="button" className="studioLink centralOpen" onClick={() => navigateToAppRoute("calendar")}>Abrir ›</button></header>
          {cal ? <ul className="centralStages">{Object.entries(cal.counts).map(([stage, value]) => <li key={stage} className={`is-${stage}`}><b>{value}</b><span>{STAGES[stage as keyof typeof STAGES] || stage}</span></li>)}</ul> : <p className="libHint">Fluxo do calendário indisponível.</p>}
        </section>

        <section className="centralCard" aria-label="Próximas entregas">
          <header><h2>Próximas entregas</h2><button type="button" className="studioLink centralOpen" onClick={() => navigateToAppRoute("calendar")}>Abrir ›</button></header>
          {cal?.upcoming.length ? <ul className="centralList">{cal.upcoming.map((post) => { const when = localParts(post.scheduled_at); return <li key={post.id}><small>{when.label} · {when.time} · {STUDIO_FORMATS[post.format]}</small><span>{post.title}</span></li>; })}</ul> : <p className="libHint">Nenhuma postagem programada no período.</p>}
          {tasks?.available && tasks.next?.length ? <><h3>Próximas tarefas</h3><ul className="centralList">{tasks.next.map((task) => <li key={`${task.title}:${task.due_date}`}><small>{task.due_date ? `${task.due_date.slice(8, 10)}/${task.due_date.slice(5, 7)}` : "Sem prazo"}</small><span>{task.title}</span></li>)}</ul></> : null}
        </section>
      </div>

      {n ? <section aria-labelledby="central-results-title">
        <div className="centralSectionHead"><h2 id="central-results-title">Resultados disponíveis</h2><p>Indicadores persistidos para o período selecionado.</p></div>
        <div className="centralNumbers">
          <KpiFigure hero label="Faturamento da loja" value={formatCurrency(n.faturamento)} rawValue={n.faturamento ?? undefined} delta={n.end ? `até ${n.end.slice(8, 10)}/${n.end.slice(5, 7)}` : "período sem fechamento"} />
          <KpiFigure label="Investimento em mídia" value={formatCurrency(n.investimento)} rawValue={n.investimento ?? undefined} />
          <KpiFigure label="Retorno por R$ 1 investido" value={n.retorno != null ? formatCurrency(n.retorno) : "—"} />
          <KpiFigure label="Pedidos" value={formatInteger(n.pedidos)} />
          {n.melhor_campanha ? <p className="centralBest">Campanha que mais vendeu: <b>{n.melhor_campanha.campanha}</b> · {n.melhor_campanha.pedidos} pedido(s) · {formatCurrency(n.melhor_campanha.vendas)}</p> : null}
        </div>
      </section> : <p className="centralUnavailable">Resultados comerciais não estão disponíveis para este período.</p>}

      <details className="centralDetails">
        <summary>Ver detalhes operacionais</summary>
        <HomeChannels />
        <div className="centralGrid">
          <Card title="Mídia On" route="media" empty={media ? null : "Sem plano de mídia salvo para este mês."}>
            {media ? <><p className="libHint">{media.objetivo ? `Objetivo: ${media.objetivo}. ` : ""}{media.verba ? `Verba do mês: ${formatCurrency(media.verba)}. ` : ""}Dia {media.elapsed_days} de {media.days_in_month}.</p>
              <ul className="centralBars">{media.channels.map((channel) => { const pct = channel.planned_spend ? Math.min(100, Math.round((channel.spent / channel.planned_spend) * 100)) : 0; return <li key={channel.channel}>
                <div><b>{channel.label}</b><span>{formatCurrency(channel.spent)}{channel.planned_spend ? ` de ${formatCurrency(channel.planned_spend)}` : ""}</span></div>
                {channel.planned_spend ? <div className="centralBar" role="img" aria-label={`${pct}% da verba usada`}><i style={{ width: `${pct}%` }} /><em style={{ left: `${Math.min(100, Math.round(((channel.expected_to_date || 0) / channel.planned_spend) * 100))}%` }} /></div> : null}
                <small>{channel.roas != null ? `ROAS ${channel.roas.toFixed(2).replace(".", ",")}` : ""}{channel.pace ? ` · ritmo ${Math.round(channel.pace * 100)}% do planejado` : ""}</small>
              </li>; })}</ul></> : null}
          </Card>

          {view.agency ? <Card title="Campanhas (Social Media)" route="campaigns" empty={view.campaigns?.length ? null : "Nenhuma campanha em andamento."}>
            <ul className="centralList">{(view.campaigns || []).map((campaign) => <li key={campaign.id}><small>{campaign.status === "pronta" ? "Pronta" : "Rascunho"}{campaign.start ? ` · ${campaign.start.slice(8, 10)}/${campaign.start.slice(5, 7)}` : ""}{campaign.end ? ` a ${campaign.end.slice(8, 10)}/${campaign.end.slice(5, 7)}` : ""} · {campaign.posts_no_calendario} post(s) no Calendário</small><span>{campaign.name}</span></li>)}</ul>
          </Card> : null}

          <Card title="Clipping" route="clipping" empty={clip ? null : "Sem notícias nas últimas semanas."}>
            {clip ? <><p className="centralClipWeek"><b>{clip.week.current.marca ?? 0}</b> menções da marca em 7 dias · <span className="is-pos">{clip.week.current.positivo ?? 0} positivas</span> · <span className="is-neg">{clip.week.current.negativo ?? 0} negativas</span></p>
              <ul className="centralList">{clip.latest.map((item) => <li key={item.id}><small>{item.source || "Fonte"}{item.sentiment ? ` · ${SENT[item.sentiment] || item.sentiment}` : ""}</small><a href={item.url} target="_blank" rel="noreferrer noopener">{item.title} ↗</a></li>)}</ul></> : null}
          </Card>

          <Card title={view.agency ? "Tarefas" : "Em andamento com a Mugô"} route="tasks" empty={tasks?.available ? (tasks.open ? null : "Nenhuma tarefa aberta.") : "Tarefas do CRM indisponíveis agora."}>
            {tasks?.available ? <p className="libHint">{tasks.open} aberta(s){tasks.late ? ` · ${tasks.late} atrasada(s)` : ""}</p> : null}
          </Card>
        </div>
      </details>
    </> : null}
  </div></Shell>;
}
