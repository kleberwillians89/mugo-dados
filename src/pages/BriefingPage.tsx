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
  { key: "social_media", label: "Social Media", route: "campaigns", hint: "Gera a Matriz e os posts com este foco" },
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

    <Forwarding brief={brief} people={people} busy={busy} disabled={busy !== null || waiting} run={run} onChange={onChange} />

    <details className="briefSection"><summary>Pedido original</summary><p className="briefRequest">{brief.request}</p>
      {brief.links?.length ? <ul>{brief.links.map((u) => <li key={u}><a href={u} target="_blank" rel="noopener noreferrer">{u}</a></li>)}</ul> : null}</details>
    <button type="button" className="ds-link briefArchive" disabled={busy !== null} onClick={async () => { const r = await run("arch", () => updateBrief(brief.id, { status: "arquivado" }), "Não foi possível arquivar."); if (r) onChange(r.brief); }}>Arquivar briefing</button>
  </article>;
}

/**
 * Encaminhamento: um só bloco para levar o briefing a uma tela (Social Media, Mídia On…) e/ou criar a tarefa de quem
 * faz, com prazo. Usa os mesmos serviços de antes (envio ao destino e tarefa do briefing): nenhum sistema novo de tarefas.
 */
function Forwarding({ brief, people, busy, disabled, run, onChange }: { brief: Brief; people: Person[] | null; busy: string | null; disabled: boolean;
  run: Run; onChange: (b: Brief) => void }) {
  const b = brief.brief;
  const sentTo = brief.destinations || {};
  const tasks = brief.tasks || [];
  const suggestedDest = (b.destinations || []).filter((d) => DESTINATIONS.some((x) => x.key === d.key));
  const suggestedRoles = b.roles || [];
  const firstDest = suggestedDest.find((d) => sentTo[d.key]?.status !== "feito")?.key || "";
  const firstRole = suggestedRoles.find((r) => !tasks.some((t) => t.role === r.role))?.role || "";
  const [dest, setDest] = useState<BriefDestination | "">(firstDest);
  const [role, setRole] = useState<BriefingRole | "">(firstRole);
  const [user, setUser] = useState("");
  const [due, setDue] = useState("");
  const [note, setNote] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const person = (people || []).find((p) => p.user_id === user);
  const destInfo = DESTINATIONS.find((d) => d.key === dest);
  const destWhy = dest ? suggestedDest.find((d) => d.key === dest)?.why : undefined;
  const roleWhat = role ? suggestedRoles.find((r) => r.role === role)?.what : undefined;
  const needsPerson = Boolean(role) && Boolean(people?.length) && !user;
  const sending = busy === "fwd";
  const roleOptions = [...suggestedRoles.map((r) => r.role), ...(Object.keys(BRIEFING_ROLES) as BriefingRole[]).filter((r) => !suggestedRoles.some((s) => s.role === r))];

  async function confirm() {
    setDone(null);
    const steps: string[] = [];
    let latest: Brief | null = null;
    let failed: string | null = null;
    const ok = await run("fwd", async () => {
      if (dest) {
        const sent = (await sendBrief(brief.id, dest)).brief;
        latest = sent;
        const label = DESTINATIONS.find((d) => d.key === dest)?.label || dest;
        // O destino responde "falhou" escrito no próprio destino: não segue para a tarefa sem a pessoa ver.
        if (sent.destinations?.[dest]?.status === "falhou") { failed = `Não foi possível levar para ${label}: ${sent.destinations[dest]?.detail || "tente de novo"}.`; return true; }
        steps.push(label);
      }
      if (role) {
        latest = (await briefTask(brief.id, { role, assignee_user_id: person?.user_id || null, assignee_name: person?.name || null,
          due_date: due || null, note: note.trim() || null })).brief;
        steps.push(`tarefa de ${person?.name || BRIEFING_ROLES[role]}`);
      }
      return true;
    }, "Não foi possível encaminhar.");
    // O que já foi feito antes de uma falha continua valendo (e aparece na lista abaixo).
    if (latest) onChange(latest);
    if (ok && failed) setDone(failed);
    else if (ok) { setDone(`✓ Encaminhado: ${steps.join(" + ")}.`); setUser(""); setNote(""); setDue(""); }
  }

  return <section className="briefSection" aria-label="Encaminhamento">
    <h3>Encaminhamento</h3>
    <div className="briefPerson briefEdit">
      <label>Destino<select value={dest} disabled={disabled} onChange={(e) => setDest(e.target.value as BriefDestination | "")}>
        <option value="">Só a tarefa (não levar para outra tela)</option>
        {DESTINATIONS.map((d) => <option key={d.key} value={d.key}>{d.label}{suggestedDest.some((s) => s.key === d.key) ? " · sugerido" : ""}{sentTo[d.key]?.status === "feito" ? " · já enviado" : ""}</option>)}
      </select>{destInfo ? <small className="libHint">{destWhy || destInfo.hint}</small> : null}</label>
      <label>Função<select value={role} disabled={disabled} onChange={(e) => setRole(e.target.value as BriefingRole | "")}>
        <option value="">Sem tarefa (só levar para a tela)</option>
        {roleOptions.map((r) => <option key={r} value={r}>{BRIEFING_ROLES[r]}{suggestedRoles.some((s) => s.role === r) ? " · sugerido" : ""}</option>)}
      </select>{roleWhat ? <small className="libHint">{roleWhat}</small> : null}</label>
      {role ? <>
        <label>Responsável<select value={user} disabled={disabled} onChange={(e) => setUser(e.target.value)} aria-label="Responsável">
          <option value="">{people === null ? "Carregando…" : people.length ? "Quem vai fazer?" : "Sem integrantes: fica sem responsável"}</option>
          {(people || []).map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
        </select></label>
        <label>Prazo<input type="date" value={due} disabled={disabled} onChange={(e) => setDue(e.target.value)} aria-label="Prazo" /></label>
        <label>Recado<input value={note} disabled={disabled} onChange={(e) => setNote(e.target.value)} placeholder="Opcional" aria-label="Recado" /></label>
      </> : null}
      <div className="postBriefingActions">
        <button type="button" className="ds-button is-primary" disabled={disabled || (!dest && !role) || needsPerson} onClick={() => void confirm()}>
          {sending ? "Encaminhando…" : "Confirmar encaminhamento"}</button>
      </div>
      {done ? <p className={done.startsWith("✓") ? "studioOk" : "studioError"} role="status">{done}</p> : null}
    </div>

    {Object.keys(sentTo).length || tasks.length ? <ul className="briefDestinations" aria-label="Já encaminhado">
      {DESTINATIONS.filter((d) => sentTo[d.key]).map((d) => {
        const sent = sentTo[d.key]!;
        return <li key={d.key} className={sent.status === "feito" ? "is-done" : ""}>
          <div><b>{d.label}</b><small>{sent.detail}</small>
            {sent.status === "feito" ? <a href={getPathForRoute(d.route)}>Abrir {d.label} →</a> : null}</div>
          {sent.status === "falhou" ? <button type="button" className="ds-button" disabled={disabled}
            onClick={async () => { const r = await run(`d:${d.key}`, () => sendBrief(brief.id, d.key), "Não foi possível enviar."); if (r) onChange(r.brief); }}>
            {busy === `d:${d.key}` ? "Enviando…" : "Tentar de novo"}</button> : null}
        </li>;
      })}
      {tasks.map((t) => <li key={t.task_id} className="is-done"><div><b>{BRIEFING_ROLES[t.role] || t.role}</b><small className="studioOk">✓ Tarefa de {t.name}</small></div></li>)}
    </ul> : null}
  </section>;
}
