import { useCallback, useEffect, useMemo, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { listAssignees, type Person } from "../app/crm";
import { getPathForRoute, type AppRoute } from "../app/routes";
import { BRIEFING_ROLES, type BriefingRole } from "../app/studio";
import { approveBrief, briefTask, createBrief, listBriefs, regenerateBrief, sendBrief, updateBrief,
  type Brief, type BriefDestination, type BriefPatch } from "../app/briefs";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/studio.css";

const DESTINATIONS: { key: BriefDestination; label: string; route: AppRoute; hint: string }[] = [
  { key: "social_media", label: "Social Media", route: "campaigns", hint: "Roda a esteira de agentes com este foco" },
  { key: "midia_on", label: "Mídia On", route: "media", hint: "Gera a estratégia de mídia paga" },
  { key: "clipping", label: "Clipping", route: "clipping", hint: "Passa a monitorar os termos" },
  { key: "redacao", label: "Redação", route: "redacao", hint: "Abre um documento com o briefing" },
  { key: "criadores", label: "Criadores", route: "creators", hint: "Cria a lista e sugere perfis" },
];
const STATUS: Record<Brief["status"], string> = { aguardando_equipe: "Aguardando a equipe", pronto: "Pronto para distribuir",
  distribuido: "Em andamento", arquivado: "Arquivado" };
const fmtDate = (iso?: string | null) => (iso ? new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) : "");
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

/**
 * Briefing: a porta de entrada dos pedidos. A pessoa digita o pedido; a IA monta um briefing curto com o contexto
 * do cliente; a equipe confere e distribui para as telas e cria a tarefa de cada pessoa. O cliente também abre
 * pedido e acompanha a versão curta.
 */
export default function BriefingPage() {
  const clientId = getActiveClientId();
  const [briefs, setBriefs] = useState<Brief[]>([]);
  const [team, setTeam] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [request, setRequest] = useState("");
  const [links, setLinks] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [people, setPeople] = useState<Person[] | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await listBriefs();
      if (getActiveClientId() !== clientId) return;
      setBriefs(r.briefs); setTeam(r.team);
      setOpenId((id) => id && r.briefs.some((b) => b.id === id) ? id : r.briefs[0]?.id || null);
    } catch (cause) { setError(message(cause, "Não foi possível carregar os briefings.")); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!team) return;
    listAssignees().then((r) => setPeople(r.available ? r.people : [])).catch(() => setPeople([]));
  }, [team, clientId]);

  const replace = (b: Brief) => setBriefs((list) => list.map((x) => (x.id === b.id ? { ...x, ...b } : x)));
  const run = async <T,>(key: string, fn: () => Promise<T>, fallback: string): Promise<T | null> => {
    setBusy(key); setError(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  };

  async function submit() {
    const urls = links.split(/\s+/).map((u) => u.trim()).filter((u) => u.startsWith("https://"));
    const r = await run("create", () => createBrief(request.trim(), urls), "Não foi possível montar o briefing.");
    if (r) { setBriefs((list) => [r.brief, ...list]); setOpenId(r.brief.id); setRequest(""); setLinks(""); }
  }

  const current = useMemo(() => briefs.find((b) => b.id === openId) || null, [briefs, openId]);

  return <Shell title="Briefing" variant="editorial"><div className="ds-page studioPage briefPage">
    <PageHeader company={getActiveClientName() || "empresa"} title="Briefing" />
    <section className="briefComposer" aria-label="Novo pedido">
      <label htmlFor="brief-request"><b>O que precisa?</b><span>{team ? "Escreva o pedido como chegou. A IA monta o briefing com o contexto da marca."
        : "Conte o que você precisa. A equipe Mugô recebe na hora e devolve o plano."}</span></label>
      <textarea id="brief-request" rows={3} maxLength={4000} value={request} placeholder="Ex.: campanha de Black Friday com foco em decant, verba de 3 mil, até dia 27"
        onChange={(e) => setRequest(e.target.value)} />
      <div className="briefComposerRow">
        <input value={links} onChange={(e) => setLinks(e.target.value)} placeholder="Links de referência (opcional, separados por espaço)" aria-label="Links de referência" />
        <button type="button" className="ds-button is-primary" disabled={busy !== null || request.trim().length < 3} onClick={() => void submit()}>
          {busy === "create" ? "Montando o briefing…" : team ? "Montar briefing" : "Enviar pedido"}</button>
      </div>
    </section>
    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}

    <div className="briefLayout">
      <aside className="briefList" aria-label="Briefings">
        {loading && !briefs.length ? <p className="libHint">Carregando…</p> : null}
        {!loading && !briefs.length ? <p className="libHint">Nenhum pedido ainda.</p> : null}
        {briefs.map((b) => <button key={b.id} type="button" className={`briefListItem${b.id === openId ? " is-open" : ""}`} onClick={() => setOpenId(b.id)}>
          <b>{b.brief.title}</b>
          <small><span className={`briefStatus is-${b.status}`}>{STATUS[b.status]}</span>{b.brief.deadline ? ` · até ${fmtDate(b.brief.deadline)}` : ""}</small>
          {b.progress?.total ? <span className="briefBar" aria-label={`${b.progress.done} de ${b.progress.total} tarefas concluídas`}>
            <i style={{ width: `${Math.round((b.progress.done / b.progress.total) * 100)}%` }} /></span> : null}
        </button>)}
      </aside>
      {current ? (team
        ? <TeamBrief key={current.id} brief={current} people={people} busy={busy} run={run} onChange={replace} />
        : <ClientBrief brief={current} />) : null}
    </div>
  </div></Shell>;
}

type Run = <T>(key: string, fn: () => Promise<T>, fallback: string) => Promise<T | null>;

function ClientBrief({ brief }: { brief: Brief }) {
  const b = brief.brief;
  return <article className="briefDetail" aria-label={b.title}>
    <header><span className={`briefStatus is-${brief.status}`}>{STATUS[brief.status]}</span><h2>{b.title}</h2></header>
    {b.client_summary ? <p className="briefLead">{b.client_summary}</p> : <p className="libHint">A equipe Mugô está montando o plano.</p>}
    <dl className="briefFacts">
      {b.deadline ? <><dt>Prazo</dt><dd>{fmtDate(b.deadline)}</dd></> : null}
      {b.goal ? <><dt>Como vamos medir</dt><dd>{b.goal}</dd></> : null}
      {brief.progress?.total ? <><dt>Andamento</dt><dd>{brief.progress.done} de {brief.progress.total} entregas concluídas</dd></> : null}
    </dl>
    <details><summary>Seu pedido</summary><p className="briefRequest">{brief.request}</p></details>
  </article>;
}

function TeamBrief({ brief, people, busy, run, onChange }: { brief: Brief; people: Person[] | null; busy: string | null; run: Run; onChange: (b: Brief) => void }) {
  const b = brief.brief;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<BriefPatch>({});
  const [redo, setRedo] = useState("");
  const waiting = brief.status === "aguardando_equipe";
  const suggested = new Set((b.destinations || []).map((d) => d.key));
  const why = (k: BriefDestination) => b.destinations?.find((d) => d.key === k)?.why;
  const roles = (b.roles || []).map((r) => r.role);
  const [extra, setExtra] = useState<BriefingRole[]>([]);
  const rows: BriefingRole[] = [...roles, ...extra.filter((r) => !roles.includes(r))];

  async function save() {
    const r = await run("save", () => updateBrief(brief.id, draft), "Não foi possível salvar.");
    if (r) { onChange(r.brief); setEditing(false); setDraft({}); }
  }
  const field = (key: keyof BriefPatch, label: string, long = false) => {
    const value = (key in draft ? draft[key] : (b as Record<string, unknown>)[key]) as string | undefined;
    return <label key={key}>{label}{long ? <textarea rows={2} value={value || ""} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
      : <input type={key === "deadline" ? "date" : "text"} value={value || ""} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />}</label>;
  };

  return <article className="briefDetail" aria-label={b.title}>
    <header>
      <span className={`briefStatus is-${brief.status}`}>{STATUS[brief.status]}</span>
      <h2>{b.title}</h2>
      <small className="libHint">{brief.created_side === "cliente" ? `Pedido do cliente${brief.created_by_name ? ` (${brief.created_by_name})` : ""}` : `Aberto por ${brief.created_by_name || "equipe"}`} · {new Date(brief.created_at).toLocaleDateString("pt-BR")}</small>
    </header>
    {waiting ? <div className="ds-notice" role="status"><p className="ds-noticeTitle">Pedido do cliente: confira o briefing e aprove para distribuir.</p>
      <button type="button" className="ds-button is-primary" disabled={busy !== null} onClick={async () => { const r = await run("approve", () => approveBrief(brief.id), "Não foi possível aprovar."); if (r) onChange(r.brief); }}>Aprovar briefing</button></div> : null}

    {editing ? <div className="briefEdit">
      {field("title", "Título")}{field("summary", "Resumo", true)}{field("objective", "Objetivo")}{field("key_message", "Mensagem")}
      {field("audience", "Público")}{field("deadline", "Prazo")}{field("goal", "Meta (como provamos o resultado)")}{field("client_summary", "Versão para o cliente", true)}
      <div className="postBriefingActions"><button type="button" className="ds-button is-primary" disabled={busy !== null} onClick={() => void save()}>Salvar</button>
        <button type="button" className="ds-button" onClick={() => { setEditing(false); setDraft({}); }}>Cancelar</button></div>
    </div> : <>
      {b.summary ? <p className="briefLead">{b.summary}</p> : null}
      <dl className="briefFacts">
        {b.objective ? <><dt>Objetivo</dt><dd>{b.objective}</dd></> : null}
        {b.key_message ? <><dt>Mensagem</dt><dd>{b.key_message}</dd></> : null}
        {b.audience ? <><dt>Público</dt><dd>{b.audience}</dd></> : null}
        {b.deadline ? <><dt>Prazo</dt><dd>{fmtDate(b.deadline)}</dd></> : null}
        {b.goal ? <><dt>Meta</dt><dd>{b.goal}</dd></> : null}
        {b.deliverables?.length ? <><dt>Entregáveis</dt><dd>{b.deliverables.join(" · ")}</dd></> : null}
        {b.avoid?.length ? <><dt>Não fazer</dt><dd>{b.avoid.join(" · ")}</dd></> : null}
      </dl>
      {b.client_summary ? <p className="briefClientLine"><b>O cliente vê:</b> {b.client_summary}</p> : null}
      <div className="postBriefingActions">
        <button type="button" className="ds-button" onClick={() => setEditing(true)}>Editar</button>
        <input className="briefRedo" value={redo} onChange={(e) => setRedo(e.target.value)} placeholder="Refazer pedindo… (opcional)" aria-label="Pedido para refazer" />
        <button type="button" className="ds-button" disabled={busy !== null} onClick={async () => { const r = await run("redo", () => regenerateBrief(brief.id, redo.trim() || undefined), "Não foi possível refazer."); if (r) { onChange(r.brief); setRedo(""); } }}>
          {busy === "redo" ? "Refazendo…" : "Refazer com IA"}</button>
      </div>
    </>}

    <section className="briefSection" aria-label="Destinos">
      <h3>Levar para</h3>
      <ul className="briefDestinations">{DESTINATIONS.map((d) => {
        const sent = brief.destinations?.[d.key];
        return <li key={d.key} className={`${suggested.has(d.key) ? "is-suggested" : ""}${sent?.status === "feito" ? " is-done" : ""}`}>
          <div><b>{d.label}</b><small>{sent ? sent.detail : why(d.key) || d.hint}</small>
            {sent?.status === "feito" ? <a href={getPathForRoute(d.route)}>Abrir {d.label} →</a> : null}</div>
          <button type="button" className={`ds-button${suggested.has(d.key) && !sent ? " is-primary" : ""}`} disabled={busy !== null || waiting}
            onClick={async () => { const r = await run(`d:${d.key}`, () => sendBrief(brief.id, d.key), "Não foi possível enviar."); if (r) onChange(r.brief); }}>
            {busy === `d:${d.key}` ? "Enviando…" : sent?.status === "feito" ? "Enviar de novo" : sent?.status === "falhou" ? "Tentar de novo" : "Enviar"}</button>
        </li>;
      })}</ul>
    </section>

    <section className="briefSection" aria-label="Pessoas">
      <h3>Quem faz o quê</h3>
      <div className="briefPeople">
      {rows.map((role) => <PersonRow key={role} role={role} what={b.roles?.find((r) => r.role === role)?.what} people={people}
        disabled={busy !== null || waiting} done={(brief.tasks || []).filter((t) => t.role === role)}
        onCreate={async (input) => { const r = await run(`t:${role}`, () => briefTask(brief.id, { role, ...input }), "Não foi possível criar a tarefa."); if (r) onChange(r.brief); return Boolean(r); }} />)}
      </div>
      <label className="briefAddRole">Outra função<select value="" onChange={(e) => { if (e.target.value) setExtra([...extra, e.target.value as BriefingRole]); }}>
        <option value="">Adicionar…</option>
        {(Object.keys(BRIEFING_ROLES) as BriefingRole[]).filter((r) => !rows.includes(r)).map((r) => <option key={r} value={r}>{BRIEFING_ROLES[r]}</option>)}
      </select></label>
    </section>

    <details className="briefSection"><summary>Pedido original</summary><p className="briefRequest">{brief.request}</p>
      {brief.links?.length ? <ul>{brief.links.map((u) => <li key={u}><a href={u} target="_blank" rel="noopener noreferrer">{u}</a></li>)}</ul> : null}</details>
    <button type="button" className="ds-link briefArchive" disabled={busy !== null} onClick={async () => { const r = await run("arch", () => updateBrief(brief.id, { status: "arquivado" }), "Não foi possível arquivar."); if (r) onChange(r.brief); }}>Arquivar briefing</button>
  </article>;
}

function PersonRow({ role, what, people, disabled, done, onCreate }: { role: BriefingRole; what?: string; people: Person[] | null; disabled: boolean;
  done: { name: string }[]; onCreate: (input: { assignee_user_id: string | null; assignee_name: string | null; due_date: string | null; note: string | null }) => Promise<boolean> }) {
  const [user, setUser] = useState("");
  const [due, setDue] = useState("");
  const [note, setNote] = useState("");
  const person = (people || []).find((p) => p.user_id === user);
  return <div className="briefPerson">
    <div className="briefPersonRole"><b>{BRIEFING_ROLES[role]}</b>{what ? <small>{what}</small> : null}
      {done.length ? <small className="studioOk">✓ Tarefa de {done.map((d) => d.name).join(", ")}</small> : null}</div>
    <div className="briefPersonForm">
    <select value={user} onChange={(e) => setUser(e.target.value)} aria-label={`Pessoa para ${BRIEFING_ROLES[role]}`} disabled={disabled}>
      <option value="">{people === null ? "Carregando…" : people.length ? "Quem?" : "Sem integrantes"}</option>
      {(people || []).map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
    </select>
    <input type="date" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Prazo" disabled={disabled} />
    <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Recado (opcional)" aria-label="Recado" disabled={disabled} />
    <button type="button" className="ds-button" disabled={disabled || (Boolean(people?.length) && !user)}
      onClick={async () => { if (await onCreate({ assignee_user_id: person?.user_id || null, assignee_name: person?.name || null, due_date: due || null, note: note.trim() || null })) { setUser(""); setNote(""); } }}>Criar tarefa</button>
    </div>
  </div>;
}
