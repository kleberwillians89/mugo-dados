import { useEffect, useState } from "react";
import { createTask } from "../../app/crm";
import { CRITICALITY_LABEL, KIND_LABEL, SENTIMENT_LABEL, type Clipping as Item, type ClippingInsights, type ClippingView } from "../../app/contentOps";
import { getMetaPermissions, type MetaFeature } from "../../app/metaLive";
import { clippingHeadline } from "../../app/clippingText";
import "../../styles/metaLive.css";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }) : "");
const toneOf = (s: string | null | undefined) => (s === "positivo" ? "ok" : s === "negativo" ? "bad" : s === "misto" ? "warn" : "neu");

type Props = {
  company: string; view: ClippingView; insights: ClippingInsights | null; canManage: boolean; busy: string | null;
  onCalendar: (item: Item) => void; onMark: (item: Item, status: "lido" | "arquivado") => void; onOpenAll: () => void;
};

/** Aba "Hoje": o que pede ação primeiro, depois o que é novo. As abas de sempre continuam ao lado. */
export default function ClippingToday({ company, view, insights, canManage, busy, onCalendar, onMark, onOpenAll }: Props) {
  const [mentions, setMentions] = useState<MetaFeature | null>(null);
  const [taskBusy, setTaskBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    let alive = true;
    getMetaPermissions().then((p) => { if (alive) setMentions(p.features.find((f) => f.key === "mentions") || null); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);

  async function task(item: { id: string; title: string; url: string; source: string | null; risks?: string[] }) {
    setTaskBusy(item.id); setNote(null);
    try {
      await createTask({ title: `Clipping: ${item.title}`.slice(0, 200), category: "Clipping",
        notes: [item.url, item.source ? `Fonte: ${item.source}` : "", item.risks?.length ? `Riscos: ${item.risks.join(" · ")}` : ""].filter(Boolean).join("\n") });
      setNote({ ok: true, text: "Tarefa criada em Tarefas." });
    } catch (cause) {
      setNote({ ok: false, text: cause instanceof Error && cause.message ? cause.message : "Não foi possível criar a tarefa." });
    } finally { setTaskBusy(null); }
  }

  const week = view.week;
  const settings = view.settings;
  const total = week ? week.current.positivo + week.current.neutro + week.current.negativo : 0;
  const share = (() => {
    const rows = Array.isArray(insights?.mentions) ? insights.mentions : [];
    const sum = rows.reduce((n, r) => n + r.count, 0);
    const own = rows.filter((r) => r.key.startsWith("marca:")).reduce((n, r) => n + r.count, 0);
    return sum ? Math.round((own / sum) * 100) : null;
  })();
  const critical = Array.isArray(insights?.critical) ? insights.critical : [];
  const criticalIds = new Set(critical.map((c) => c.id));
  const chances = (view.items || []).filter((i) => i.status === "novo" && i.opportunities?.length && (i.relevance ?? 0) >= 60 && !criticalIds.has(i.id)).slice(0, 2);
  const fresh = (view.items || []).filter((i) => i.status === "novo" && i.relevant !== false && !criticalIds.has(i.id) && !chances.includes(i)).slice(0, 8);
  const versus = (Array.isArray(insights?.mentions) ? insights.mentions : []).slice(0, 5);
  const maxVs = Math.max(1, ...versus.map((v) => v.count));

  return <div className="clipToday">
    {week ? <p className="clipHeadline" role="status">{clippingHeadline(company, week)}</p> : null}

    <div className="clipSources" aria-label="Fontes">
      <b>Fontes</b>
      <span className="mlChip is-ok">Google Notícias · todo dia às 7h40</span>
      {settings?.feeds?.length ? <span className="mlChip is-ok">{settings.feeds.length} fonte(s) RSS própria(s)</span> : null}
      {mentions ? <span className={`mlChip is-${mentions.state === "ok" ? "ok" : "bad"}`}>{mentions.state === "ok" ? "Página e menções da Meta liberadas" : "Menções no Instagram: falta permissão"}</span> : null}
      {settings?.last_run_at ? <small className="mlMuted">Última busca: {new Date(settings.last_run_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</small> : null}
    </div>

    {week ? <div className="mlKpis" aria-label="Últimos 7 dias">
      <div className="mlCard mlKpi"><span className="mlLbl">Notícias da marca · 7 dias</span><b>{week.current.marca}</b>
        <small>{week.marca_variacao > 0 ? `+${week.marca_variacao}` : week.marca_variacao} vs. semana anterior</small></div>
      <div className="mlCard mlKpi"><span className="mlLbl">Como falaram</span>
        {total ? <div className="clipMood" role="img" aria-label={`${week.current.positivo} positivas, ${week.current.neutro} neutras, ${week.current.negativo} negativas`}>
          <span className="is-pos" style={{ flex: week.current.positivo }} /><span className="is-neu" style={{ flex: week.current.neutro }} /><span className="is-neg" style={{ flex: week.current.negativo }} /></div> : <b>—</b>}
        <small>{week.current.positivo} bem · {week.current.neutro} neutras · {week.current.negativo} mal</small></div>
      <div className="mlCard mlKpi"><span className="mlLbl">Espaço da marca na conversa</span><b>{share == null ? "—" : `${share}%`}</b>
        <small>das menções, contra os concorrentes (30 dias)</small></div>
      <div className="mlCard mlKpi"><span className="mlLbl">Concorrentes · 7 dias</span><b>{week.current.concorrente}</b><small>notícias sobre eles</small></div>
    </div> : null}

    {note ? <p className={note.ok ? "studioOk" : "studioError"} role={note.ok ? "status" : "alert"}>{note.text}</p> : null}

    {critical.length || chances.length ? <section className="mlBlock" aria-labelledby="clip-att">
      <div className="mlRow"><h3 id="clip-att">Precisa de atenção</h3>{critical.length ? <span className="mlChip is-bad">{critical.length}</span> : null}</div>
      <div className="mlCamps">
        {critical.map((c) => <article className="mlCard clipAtt is-critical" key={c.id}>
          <div className="mlChips"><span className="mlChip is-bad">{c.criticality ? CRITICALITY_LABEL[c.criticality] : "Crítica"}{c.sentiment ? ` · ${SENTIMENT_LABEL[c.sentiment].toLowerCase()}` : ""}</span>
            <small className="mlMuted">{c.source || "Fonte"} · {when(c.published_at)}</small></div>
          <h4><a href={c.url} target="_blank" rel="noreferrer noopener">{c.title}</a></h4>
          {c.risks?.length ? <p>Risco: {c.risks.slice(0, 2).join(" · ")}</p> : null}
          {canManage ? <div className="mlActions">
            <button type="button" className="ds-button is-primary" disabled={taskBusy === c.id} onClick={() => void task(c)}>{taskBusy === c.id ? "Criando…" : "Criar tarefa para a equipe"}</button>
            <a className="ds-button" href={c.url} target="_blank" rel="noreferrer noopener">Abrir matéria</a>
          </div> : null}
        </article>)}
        {chances.map((i) => <article className="mlCard clipAtt" key={i.id}>
          <div className="mlChips"><span className="mlChip is-ok">Oportunidade</span><span className="mlChip is-neu">{KIND_LABEL[i.kind] || i.kind} · {i.term}</span>
            <small className="mlMuted">{i.source || "Fonte"} · {when(i.published_at || i.created_at)}</small></div>
          <h4><a href={i.url} target="_blank" rel="noreferrer noopener">{i.title}</a></h4>
          <p>{i.opportunities?.slice(0, 2).join(" · ")}</p>
          {canManage ? <div className="mlActions">
            <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => onCalendar(i)}>Virar pauta</button>
            <button type="button" className="ds-button" disabled={taskBusy === i.id} onClick={() => void task(i)}>Criar tarefa</button>
          </div> : null}
        </article>)}
      </div>
    </section> : null}

    <div className="clipTodayCols">
      <section className="mlBlock clipFeed" aria-labelledby="clip-new">
        <div className="mlRow mlSpread"><h3 id="clip-new">Novas para ler <span className="mlMuted">{fresh.length}</span></h3>
          <button type="button" className="ds-button" onClick={onOpenAll}>Ver todas as matérias</button></div>
        {fresh.length ? fresh.map((i) => <article className="mlCard clipRow" key={i.id}>
          <div className="mlChips"><span className={`mlChip is-${toneOf(i.sentiment)}`}>{i.sentiment ? SENTIMENT_LABEL[i.sentiment] : "Sem leitura"}</span>
            <span className={`mlChip is-${i.kind === "concorrente" ? "warn" : "neu"}`}>{KIND_LABEL[i.kind] || i.kind} · {i.term}</span>
            {i.relevance != null ? <span className="mlChip is-neu">Relevância {i.relevance}</span> : null}
            <small className="mlMuted">{i.source || "Fonte"} · {when(i.published_at || i.created_at)}</small></div>
          <h4><a href={i.url} target="_blank" rel="noreferrer noopener">{i.title}</a></h4>
          {i.summary ? <p>{i.summary}</p> : null}
          {canManage ? <div className="mlRow">
            {i.status === "pauta" ? <span className="studioOk">Virou pauta</span> : <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => onCalendar(i)}>Virar pauta</button>}
            <button type="button" className="ds-button" disabled={taskBusy === i.id} onClick={() => void task(i)}>Criar tarefa</button>
            <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => onMark(i, "lido")}>Lida</button>
            <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => onMark(i, "arquivado")}>Arquivar</button>
          </div> : null}
        </article>) : <p className="mlMuted">Nada novo para ler. Tudo em dia.</p>}
      </section>

      <aside className="clipSide" aria-label="Leitura do período">
        {versus.length ? <div className="mlCard"><h3>Marca x concorrentes</h3><ul className="mlBars">{versus.map((v) => {
          const [kind, term] = v.key.split(":");
          return <li key={v.key}><span>{kind === "marca" ? <b>{term}</b> : term}</span><i aria-hidden="true"><em style={{ width: `${(v.count / maxVs) * 100}%`, ...(kind === "marca" ? {} : { background: "#8a99a3" }) }} /></i><small>{v.count}</small></li>;
        })}</ul></div> : null}
        {insights?.themes?.length ? <div className="mlCard"><h3>Assuntos do momento</h3><div className="mlChips">{insights.themes.slice(0, 8).map((t) => <span className="mlChip is-neu" key={t.key}>{t.key}</span>)}</div></div> : null}
        {canManage ? <div className="mlCard"><h3>Relatório da semana</h3><p className="mlMuted">Resumo, destaques, riscos e oportunidades, só com matérias verificadas.</p>
          <button type="button" className="ds-button is-primary" onClick={onOpenAll}>Gerar em Todas as matérias</button></div> : null}
      </aside>
    </div>
  </div>;
}
