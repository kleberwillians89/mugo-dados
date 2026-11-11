import { useCallback, useEffect, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { STAGES, STUDIO_FORMATS, getCentral, localParts, type CentralView } from "../app/studio";
import { navigateToAppRoute, type AppRoute } from "../app/routes";
import { formatCurrency, formatInteger } from "../app/dataFormat";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import AiUsageButton from "../components/studio/AiUsageButton";
import KpiFigure from "../components/data/KpiFigure";
import "../styles/studio.css";

const MONTH_NAMES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const thisMonth = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const shiftMonth = (m: string, n: number) => { const d = new Date(Number(m.slice(0, 4)), Number(m.slice(5)) - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const MODULE_ROUTE: Record<string, AppRoute> = { approval: "calendar", calendar: "calendar", media: "media", clipping: "clipping", campaigns: "campaigns", tasks: "tasks" };
const SENT: Record<string, string> = { positivo: "Positiva", neutro: "Neutra", negativo: "Negativa" };

function Card({ title, route, children, empty }: { title: string; route: AppRoute; children: React.ReactNode; empty?: string | null }) {
  return <section className="centralCard" aria-label={title}>
    <header><h2>{title}</h2><button type="button" className="studioLink centralOpen" onClick={() => navigateToAppRoute(route)}>Abrir ›</button></header>
    {empty ? <p className="libHint">{empty}</p> : children}
  </section>;
}

/** Central da marca: números da campanha, Calendário, Mídia On, Social Media, Clipping e Tarefas no mesmo lugar. */
export default function Central({ isAgency = false }: { isAgency?: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const [month, setMonth] = useState(thisMonth);
  const [view, setView] = useState<CentralView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await getCentral(month);
      if (getActiveClientId() !== clientId) return;
      setView(data);
    } catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível carregar a Central."); }
    finally { setLoading(false); }
  }, [month, clientId]);
  useEffect(() => { void load(); }, [load]);

  const n = view?.numbers;
  const cal = view?.calendar;
  const media = view?.media;
  const clip = view?.clipping;
  const tasks = view?.tasks;

  return <Shell title="Central" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Central da marca" controls={<div className="calNav">
      <button type="button" className="ds-button" aria-label="Mês anterior" onClick={() => setMonth(shiftMonth(month, -1))}>‹</button>
      <h2 className="calRange">{MONTH_NAMES[Number(month.slice(5)) - 1]} {month.slice(0, 4)}</h2>
      <button type="button" className="ds-button" aria-label="Próximo mês" onClick={() => setMonth(shiftMonth(month, 1))}>›</button>
      <AiUsageButton clientName={clientName} isAgency={isAgency} />
    </div>} />
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {loading && !view ? <p>Montando a Central com os dados de todos os módulos…</p> : null}

    {n ? <section className="centralNumbers" aria-label="Números do mês">
      <KpiFigure hero label="Faturamento da loja" value={formatCurrency(n.faturamento)} rawValue={n.faturamento ?? undefined}
        delta={n.end ? `até ${n.end.slice(8, 10)}/${n.end.slice(5, 7)}` : "mês ainda não começou"} />
      <KpiFigure label="Investimento em mídia" value={formatCurrency(n.investimento)} rawValue={n.investimento ?? undefined} />
      <KpiFigure label="Retorno por R$ 1 investido" value={n.retorno != null ? formatCurrency(n.retorno) : "—"} />
      <KpiFigure label="Pedidos" value={formatInteger(n.pedidos)} />
      {n.melhor_campanha ? <p className="centralBest">Campanha que mais vendeu: <b>{n.melhor_campanha.campanha}</b> · {n.melhor_campanha.pedidos} pedido(s) · {formatCurrency(n.melhor_campanha.vendas)}</p> : null}
    </section> : null}

    {view?.alerts.length ? <section className="centralAlerts" aria-label="O que precisa de atenção">
      <h2>O que precisa de atenção</h2>
      <ul>{view.alerts.map((a) => <li key={a.text} className={`is-${a.level}`}>
        <span>{a.text}</span>{MODULE_ROUTE[a.module] ? <button type="button" className="studioLink" onClick={() => navigateToAppRoute(MODULE_ROUTE[a.module])}>Ver</button> : null}
      </li>)}</ul>
    </section> : view ? <p className="studioOk">Nada pedindo atenção agora.</p> : null}

    {view ? <div className="centralGrid">
      <Card title="Calendário" route="calendar" empty={cal && cal.total ? null : "Nenhum post neste mês ainda."}>
        {cal ? <>
          <ul className="centralStages">{Object.entries(cal.counts).filter(([, v]) => v > 0).map(([stage, v]) => <li key={stage} className={`is-${stage}`}><b>{v}</b><span>{STAGES[stage as keyof typeof STAGES] || stage}</span></li>)}</ul>
          {cal.upcoming.length ? <><h3>Próximos posts</h3><ul className="centralList">{cal.upcoming.map((p) => { const w = localParts(p.scheduled_at); return <li key={p.id}><small>{w.label} · {w.time} · {STUDIO_FORMATS[p.format]}</small><span>{p.title}</span></li>; })}</ul></> : null}
        </> : null}
      </Card>

      <Card title="Mídia On" route="media" empty={media ? null : "Sem plano de mídia salvo para este mês."}>
        {media ? <>
          <p className="libHint">{media.objetivo ? `Objetivo: ${media.objetivo}. ` : ""}{media.verba ? `Verba do mês: ${formatCurrency(media.verba)}. ` : ""}Dia {media.elapsed_days} de {media.days_in_month}.</p>
          <ul className="centralBars">{media.channels.map((c) => { const pct = c.planned_spend ? Math.min(100, Math.round((c.spent / c.planned_spend) * 100)) : 0; return <li key={c.channel}>
            <div><b>{c.label}</b><span>{formatCurrency(c.spent)}{c.planned_spend ? ` de ${formatCurrency(c.planned_spend)}` : ""}</span></div>
            {c.planned_spend ? <div className="centralBar" role="img" aria-label={`${pct}% da verba usada`}><i style={{ width: `${pct}%` }} /><em style={{ left: `${Math.min(100, Math.round(((c.expected_to_date || 0) / c.planned_spend) * 100))}%` }} /></div> : null}
            <small>{c.roas != null ? `ROAS ${c.roas.toFixed(2).replace(".", ",")}` : ""}{c.pace ? ` · ritmo ${Math.round(c.pace * 100)}% do planejado` : ""}</small>
          </li>; })}</ul>
        </> : null}
      </Card>

      {view.agency ? <Card title="Campanhas (Social Media)" route="campaigns" empty={view.campaigns?.length ? null : "Nenhuma campanha em andamento."}>
        <ul className="centralList">{(view.campaigns || []).map((c) => <li key={c.id}><small>{c.status === "pronta" ? "Pronta" : "Rascunho"}{c.start ? ` · ${c.start.slice(8, 10)}/${c.start.slice(5, 7)}` : ""}{c.end ? ` a ${c.end.slice(8, 10)}/${c.end.slice(5, 7)}` : ""} · {c.posts_no_calendario} post(s) no Calendário</small><span>{c.name}</span></li>)}</ul>
      </Card> : null}

      <Card title="Clipping" route="clipping" empty={clip ? null : "Sem notícias nas últimas semanas."}>
        {clip ? <>
          <p className="centralClipWeek"><b>{clip.week.current.marca ?? 0}</b> menções da marca em 7 dias · <span className="is-pos">{clip.week.current.positivo ?? 0} positivas</span> · <span className="is-neg">{clip.week.current.negativo ?? 0} negativas</span></p>
          <ul className="centralList">{clip.latest.map((c) => <li key={c.id}><small>{c.source || "Fonte"}{c.sentiment ? ` · ${SENT[c.sentiment] || c.sentiment}` : ""}</small><a href={c.url} target="_blank" rel="noreferrer noopener">{c.title} ↗</a></li>)}</ul>
        </> : null}
      </Card>

      <Card title={view.agency ? "Tarefas" : "Em andamento com a Mugô"} route="tasks" empty={tasks?.available ? (tasks.open ? null : "Nenhuma tarefa aberta.") : "Tarefas do CRM indisponíveis agora."}>
        {tasks?.available ? <>
          <p className="libHint">{tasks.open} aberta(s){tasks.late ? ` · ${tasks.late} atrasada(s)` : ""}</p>
          <ul className="centralList">{(tasks.next || []).map((t) => <li key={`${t.title}:${t.due_date}`}><small>{t.due_date ? `${t.due_date.slice(8, 10)}/${t.due_date.slice(5, 7)}` : "Sem prazo"}</small><span>{t.title}</span></li>)}</ul>
        </> : null}
      </Card>
    </div> : null}
    {view?.agency ? <p className="libHint">Calendário, Social Media, Mídia On, mensagens e Clipping usam o mesmo cérebro da marca: perfil, o que o cliente aprovou, o que vendeu, o plano de mídia e as campanhas ativas.</p> : null}
  </div></Shell>;
}
