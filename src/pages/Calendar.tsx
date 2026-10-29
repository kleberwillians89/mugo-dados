import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  STUDIO_FORMATS, STUDIO_STATUS, createCalendarItem, deleteCalendarItem, generateCalendar, getBrandProfile,
  getCalendar, listToText, localParts, nextMonth, saveBrandProfile, sendForApproval, textToList, toSaoPauloIso, updateCalendarItem,
  type ApprovalCreated,
  type BrandProfile, type CalendarItem, type StudioFormat, type StudioStatus,
} from "../app/studio";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import Drawer from "../components/Drawer";
import "../styles/studio.css";

type Editing = { id?: string; date: string; time: string; format: StudioFormat; pillar: string; title: string; hook: string; caption_draft: string; rationale: string };

// Publicação continua manual (sem API de publicação da Meta por enquanto):
// a pauta aprovada vai para o compositor do Meta Business Suite.
const PUBLISHER_URL = "https://business.facebook.com/latest/composer";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

function weekKey(date: string) {
  const d = new Date(`${date}T12:00:00`);
  const monday = new Date(d);
  monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return monday.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

export default function Calendar({ canManage }: { canManage: boolean }) {
  const clientId = getActiveClientId();
  const [month, setMonth] = useState(nextMonth());
  const [items, setItems] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [rejecting, setRejecting] = useState<{ item: CalendarItem; note: string } | null>(null);
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [filter, setFilter] = useState<StudioStatus | "todos">("todos");
  const [copied, setCopied] = useState<string | null>(null);
  const [sending, setSending] = useState<{ selected: string[]; contact_name: string; contact_phone: string; message: string } | null>(null);
  const [sent, setSent] = useState<ApprovalCreated | null>(null);

  function openSend() {
    setError(null); setSent(null);
    setSending({ selected: items.filter((i) => i.status !== "rejeitado").map((i) => i.id), contact_name: "", contact_phone: "", message: "" });
  }

  async function submitSend(event: FormEvent) {
    event.preventDefault();
    if (!sending) return;
    const result = await run("send", () => sendForApproval({ month, item_ids: sending.selected, contact_name: sending.contact_name || undefined,
      contact_phone: sending.contact_phone || undefined, message: sending.message || undefined }), "Não foi possível gerar o link de aprovação.");
    if (result) { setSent(result); setSending(null); await load(); }
  }

  async function copyCaption(item: CalendarItem) {
    const text = [item.hook, item.caption_draft].filter(Boolean).join("\n\n") || item.title;
    try { await navigator.clipboard.writeText(text); setCopied(item.id); window.setTimeout(() => setCopied(null), 2500); }
    catch { setError("Não foi possível copiar. Selecione o texto da legenda e copie manualmente."); }
  }

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { const data = await getCalendar(month); if (getActiveClientId() === clientId) setItems(data.items); }
    catch (cause) { setError(message(cause, "Não foi possível carregar o calendário.")); }
    finally { setLoading(false); }
  }, [month, clientId]);
  useEffect(() => { void load(); }, [load]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { todos: items.length };
    for (const item of items) c[item.status] = (c[item.status] || 0) + 1;
    return c;
  }, [items]);

  const grouped = useMemo(() => {
    const visible = items.filter((i) => filter === "todos" || i.status === filter);
    const map = new Map<string, CalendarItem[]>();
    for (const item of visible) {
      const key = weekKey(localParts(item.scheduled_at).date);
      map.set(key, [...(map.get(key) || []), item]);
    }
    return [...map.entries()];
  }, [items, filter]);

  async function run<T>(key: string, fn: () => Promise<T>, fallback: string) {
    if (busy || getActiveClientId() !== clientId) return null;
    setBusy(key); setError(null);
    try { return await fn(); }
    catch (cause) { setError(message(cause, fallback)); return null; }
    finally { setBusy(null); }
  }

  async function generate() {
    if (items.some((i) => i.origin === "ia" && i.status === "rascunho") &&
      !window.confirm("Os rascunhos da IA deste mês serão substituídos. Itens aprovados, em revisão ou criados à mão ficam. Continuar?")) return;
    const result = await run("generate", () => generateCalendar(month), "Não foi possível gerar o calendário.");
    if (result) { setItems(result.items); setNotes(result.observacoes || []); }
  }

  async function setStatus(item: CalendarItem, status: StudioStatus, review_note?: string) {
    const result = await run(item.id, () => updateCalendarItem(item.id, { status, ...(review_note !== undefined ? { review_note } : {}) }), "Não foi possível atualizar a pauta.");
    if (result) setItems((all) => all.map((i) => (i.id === item.id ? result.item : i)));
  }

  async function remove(item: CalendarItem) {
    if (!window.confirm(`Excluir a pauta “${item.title}”?`)) return;
    const ok = await run(item.id, () => deleteCalendarItem(item.id), "Não foi possível excluir a pauta.");
    if (ok) setItems((all) => all.filter((i) => i.id !== item.id));
  }

  function openEdit(item?: CalendarItem) {
    setError(null);
    if (!item) { setEditing({ date: `${month}-01`, time: "19:00", format: "reels", pillar: "", title: "", hook: "", caption_draft: "", rationale: "" }); return; }
    const { date, time } = localParts(item.scheduled_at);
    setEditing({ id: item.id, date, time, format: item.format, pillar: item.pillar || "", title: item.title, hook: item.hook || "", caption_draft: item.caption_draft || "", rationale: item.rationale || "" });
  }

  async function submitEdit(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const body = { scheduled_at: toSaoPauloIso(editing.date, editing.time), format: editing.format, pillar: editing.pillar || undefined,
      title: editing.title, hook: editing.hook || undefined, caption_draft: editing.caption_draft || undefined, rationale: editing.rationale || undefined };
    const result = await run("edit", () => (editing.id ? updateCalendarItem(editing.id, body) : createCalendarItem(body)), "Não foi possível salvar a pauta.");
    if (result) { setEditing(null); await load(); }
  }

  async function openProfile() {
    setError(null);
    const data = await run("profile", () => getBrandProfile(), "Não foi possível carregar o perfil da marca.");
    if (data) { setProfile(data.profile); setProfileOpen(true); }
  }

  async function submitProfile(event: FormEvent) {
    event.preventDefault();
    if (!profile) return;
    const result = await run("profile-save", () => saveBrandProfile(profile), "Não foi possível salvar o perfil.");
    if (result) { setProfile(result.profile); setProfileOpen(false); }
  }

  return <Shell title="Calendário" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={getActiveClientName()} title="Calendário editorial" controls={canManage ? <div className="studioControls">
      <button type="button" className="ds-button" onClick={() => void openProfile()} disabled={Boolean(busy)}>Perfil da marca</button>
      <button type="button" className="ds-button" onClick={() => openEdit()} disabled={Boolean(busy)}>+ Pauta</button>
      <button type="button" className="ds-button" onClick={openSend} disabled={Boolean(busy) || !items.some((i) => i.status !== "rejeitado")}>Enviar ao cliente</button>
      <button type="button" className="ds-button is-primary" onClick={() => void generate()} disabled={Boolean(busy)}>{busy === "generate" ? "Gerando… (até 1 min)" : "Gerar mês com IA"}</button>
    </div> : undefined} />
    <p className="studioIntro">Dias e horários vêm do desempenho real dos posts; a IA sugere pauta, gancho e legenda. Nada é publicado sem aprovação.</p>
    <div className="studioFilters">
      <label>Mês <input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} /></label>
      <div role="tablist" aria-label="Filtrar por status" className="studioTabs">
        {(["todos", "rascunho", "em_revisao", "aprovado", "rejeitado"] as const).map((key) => (
          <button key={key} role="tab" aria-selected={filter === key} className={filter === key ? "is-active" : ""} onClick={() => setFilter(key)}>
            {key === "todos" ? "Todos" : STUDIO_STATUS[key]} <span>{counts[key] || 0}</span>
          </button>
        ))}
      </div>
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notes.length ? <ul className="studioNotes">{notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
    {loading && !items.length ? <p>Carregando calendário…</p> : null}
    {!loading && !items.length && !error ? <div className="studioEmpty"><p>Nenhuma pauta neste mês.</p>{canManage ? <p>Preencha o <b>perfil da marca</b> e clique em <b>Gerar mês com IA</b>.</p> : null}</div> : null}

    {grouped.map(([week, list]) => <section key={week} className="studioWeek">
      <h2>Semana de {week}</h2>
      <div className="studioGrid">{list.map((item) => {
        const when = localParts(item.scheduled_at);
        const basis = item.signals?.basis;
        return <article key={item.id} className={`studioCard is-${item.status}`}>
          <header>
            <div><strong className="studioDate">{when.weekday.charAt(0).toUpperCase() + when.weekday.slice(1)}, {when.label} · {when.time}</strong>
              <span className="studioChip">{STUDIO_FORMATS[item.format]}</span>{item.pillar ? <span className="studioChip is-pillar">{item.pillar}</span> : null}</div>
            <span className={`studioStatus is-${item.status}`}>{STUDIO_STATUS[item.status]}</span>
          </header>
          <h3>{item.title}</h3>
          {item.hook ? <p className="studioHook">“{item.hook}”</p> : null}
          {item.caption_draft ? <details><summary>Rascunho de legenda</summary><p className="studioCaption">{item.caption_draft}</p></details> : null}
          {item.rationale ? <p className="studioWhy">{item.rationale}</p> : null}
          <ul className="studioSignals">
            {item.signals?.seasonal ? <li>📅 {item.signals.seasonal}</li> : null}
            {basis?.hours ? <li>⏱ {basis.hours}{basis.slot_reach_index ? ` · alcance ${basis.slot_reach_index.toLocaleString("pt-BR")}x` : ""}{basis.confidence ? ` · confiança ${basis.confidence}` : ""}</li> : null}
            {item.signals?.trend ? <li>🔥 <a href={item.signals.trend.source_url} target="_blank" rel="noreferrer noopener">{item.signals.trend.topic}</a></li> : null}
            {item.signals?.palavras_evitar_encontradas?.length ? <li className="is-warning">⚠ Palavra a evitar: {item.signals.palavras_evitar_encontradas.join(", ")}</li> : null}
            {item.origin === "manual" ? <li>Criada pela equipe</li> : null}
          </ul>
          {item.review_note ? <p className="studioReview">Nota da revisão: {item.review_note}</p> : null}
          {item.status === "aprovado" ? <div className="studioPublish">
            <button type="button" onClick={() => void copyCaption(item)}>{copied === item.id ? "Legenda copiada ✓" : "Copiar legenda"}</button>
            <a href={PUBLISHER_URL} target="_blank" rel="noreferrer noopener">Abrir no Meta Business Suite ↗</a>
          </div> : null}
          {canManage ? <footer>
            {item.status !== "aprovado" ? <button className="is-approve" disabled={Boolean(busy)} onClick={() => void setStatus(item, "aprovado")}>Aprovar</button> : null}
            {item.status === "rascunho" ? <button disabled={Boolean(busy)} onClick={() => void setStatus(item, "em_revisao")}>Enviar p/ revisão</button> : null}
            {item.status !== "rejeitado" ? <button disabled={Boolean(busy)} onClick={() => setRejecting({ item, note: item.review_note || "" })}>Rejeitar</button> : null}
            {item.status === "aprovado" || item.status === "rejeitado" ? <button disabled={Boolean(busy)} onClick={() => void setStatus(item, "rascunho")}>Reabrir</button> : null}
            <button disabled={Boolean(busy)} onClick={() => openEdit(item)}>Editar</button>
            <button className="is-danger" disabled={Boolean(busy)} onClick={() => void remove(item)}>Excluir</button>
          </footer> : null}
        </article>;
      })}</div>
    </section>)}

    <Drawer open={Boolean(editing)} title={editing?.id ? "Editar pauta" : "Nova pauta"} width="lg" onClose={() => { if (!busy) setEditing(null); }}>
      {editing ? <form className="studioForm" onSubmit={submitEdit}>
        <div className="studioRow">
          <label>Data<input type="date" required value={editing.date} onChange={(e) => setEditing({ ...editing, date: e.target.value })} /></label>
          <label>Horário<input type="time" required value={editing.time} onChange={(e) => setEditing({ ...editing, time: e.target.value })} /></label>
          <label>Formato<select value={editing.format} onChange={(e) => setEditing({ ...editing, format: e.target.value as StudioFormat })}>
            {Object.entries(STUDIO_FORMATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        </div>
        <label>Pilar<input maxLength={120} value={editing.pillar} onChange={(e) => setEditing({ ...editing, pillar: e.target.value })} /></label>
        <label>Pauta<input required maxLength={200} value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} /></label>
        <label>Gancho<input maxLength={400} value={editing.hook} onChange={(e) => setEditing({ ...editing, hook: e.target.value })} /></label>
        <label>Rascunho de legenda<textarea rows={8} maxLength={4000} value={editing.caption_draft} onChange={(e) => setEditing({ ...editing, caption_draft: e.target.value })} /></label>
        <label>Por quê<textarea rows={2} maxLength={1200} value={editing.rationale} onChange={(e) => setEditing({ ...editing, rationale: e.target.value })} /></label>
        {error ? <p role="alert">{error}</p> : null}
        <div className="studioActions"><button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => setEditing(null)}>Cancelar</button><button className="ds-button is-primary" disabled={Boolean(busy)}>{busy === "edit" ? "Salvando…" : "Salvar"}</button></div>
      </form> : null}
    </Drawer>

    <Drawer open={Boolean(sending)} title="Enviar ao cliente" description="Gera um link sem login para o cliente aprovar ou pedir ajuste. Válido por 14 dias." width="lg" onClose={() => { if (!busy) setSending(null); }}>
      {sending ? <form className="studioForm" onSubmit={submitSend}>
        <fieldset><legend>Pautas ({sending.selected.length})</legend>
          {items.filter((i) => i.status !== "rejeitado").map((i) => <label key={i.id} className="studioCheck">
            <input type="checkbox" checked={sending.selected.includes(i.id)} onChange={(e) => setSending({ ...sending, selected: e.target.checked ? [...sending.selected, i.id] : sending.selected.filter((x) => x !== i.id) })} />
            {localParts(i.scheduled_at).label} · {i.title}</label>)}
        </fieldset>
        <div className="studioRow">
          <label>Nome do contato<input maxLength={120} value={sending.contact_name} onChange={(e) => setSending({ ...sending, contact_name: e.target.value })} placeholder="Ana" /></label>
          <label>WhatsApp<input inputMode="tel" maxLength={30} value={sending.contact_phone} onChange={(e) => setSending({ ...sending, contact_phone: e.target.value })} placeholder="(11) 98888-7777" /></label>
        </div>
        <label>Mensagem (opcional; sem ela usamos uma padrão)<textarea rows={3} maxLength={1000} value={sending.message} onChange={(e) => setSending({ ...sending, message: e.target.value })} /></label>
        {error ? <p role="alert">{error}</p> : null}
        <div className="studioActions"><button type="button" className="ds-button" onClick={() => setSending(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy) || !sending.selected.length}>{busy === "send" ? "Gerando…" : "Gerar link"}</button></div>
      </form> : null}
    </Drawer>

    <Drawer open={Boolean(sent)} title="Link de aprovação pronto" onClose={() => setSent(null)}>
      {sent ? <div className="studioForm">
        <p>As pautas foram para <b>Em revisão</b> e voltam aprovadas ou com o pedido de ajuste do cliente.</p>
        <label>Link<input readOnly value={sent.link} onFocus={(e) => e.currentTarget.select()} /></label>
        <div className="studioActions">
          <a className="ds-button is-primary" href={sent.whatsapp_url} target="_blank" rel="noreferrer noopener">Abrir no WhatsApp</a>
          <button type="button" className="ds-button" onClick={() => void navigator.clipboard.writeText(sent.whatsapp_text).then(() => setCopied("link"), () => undefined)}>{copied === "link" ? "Mensagem copiada ✓" : "Copiar mensagem"}</button>
        </div>
      </div> : null}
    </Drawer>

    <Drawer open={Boolean(rejecting)} title="Rejeitar pauta" onClose={() => { if (!busy) setRejecting(null); }}>
      {rejecting ? <form className="studioForm" onSubmit={(e) => { e.preventDefault(); void setStatus(rejecting.item, "rejeitado", rejecting.note).then(() => setRejecting(null)); }}>
        <p>“{rejecting.item.title}”</p>
        <label>O que precisa mudar?<textarea rows={4} maxLength={1000} value={rejecting.note} onChange={(e) => setRejecting({ ...rejecting, note: e.target.value })} /></label>
        <div className="studioActions"><button type="button" className="ds-button" onClick={() => setRejecting(null)}>Cancelar</button><button className="ds-button is-primary" disabled={Boolean(busy)}>Rejeitar</button></div>
      </form> : null}
    </Drawer>

    <Drawer open={profileOpen} title="Perfil da marca" description="Base para a IA escrever no jeito da marca." width="lg" onClose={() => { if (!busy) setProfileOpen(false); }}>
      {profile ? <form className="studioForm" onSubmit={submitProfile}>
        <label>Tom de voz<textarea rows={3} maxLength={1000} value={profile.tone_of_voice} onChange={(e) => setProfile({ ...profile, tone_of_voice: e.target.value })} /></label>
        <label>Personalidade<input maxLength={500} value={profile.personality} onChange={(e) => setProfile({ ...profile, personality: e.target.value })} /></label>
        <label>Público<textarea rows={2} maxLength={1000} value={profile.audience} onChange={(e) => setProfile({ ...profile, audience: e.target.value })} /></label>
        <fieldset className="studioPillars"><legend>Pilares de conteúdo (peso em %)</legend>
          {profile.pillars.map((p, idx) => <div key={idx} className="studioPillarRow">
            <input aria-label="Nome do pilar" required maxLength={80} value={p.name} onChange={(e) => setProfile({ ...profile, pillars: profile.pillars.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)) })} />
            <input aria-label="Peso" type="number" min={0} max={100} value={p.weight} onChange={(e) => setProfile({ ...profile, pillars: profile.pillars.map((x, i) => (i === idx ? { ...x, weight: Number(e.target.value) } : x)) })} />
            <input aria-label="Descrição" maxLength={400} placeholder="O que entra neste pilar" value={p.description} onChange={(e) => setProfile({ ...profile, pillars: profile.pillars.map((x, i) => (i === idx ? { ...x, description: e.target.value } : x)) })} />
            <button type="button" className="studioLink" aria-label="Remover pilar" onClick={() => setProfile({ ...profile, pillars: profile.pillars.filter((_, i) => i !== idx) })}>Remover</button>
          </div>)}
          {profile.pillars.length < 8 ? <button type="button" className="ds-button" onClick={() => setProfile({ ...profile, pillars: [...profile.pillars, { name: "", weight: 0, description: "" }] })}>+ Pilar</button> : null}
        </fieldset>
        <label>Palavras para usar (separe por vírgula)<input value={listToText(profile.keywords_use)} onChange={(e) => setProfile({ ...profile, keywords_use: textToList(e.target.value) })} /></label>
        <label>Palavras proibidas<input value={listToText(profile.keywords_avoid)} onChange={(e) => setProfile({ ...profile, keywords_avoid: textToList(e.target.value) })} /></label>
        <label>Hashtags<input value={listToText(profile.hashtags)} onChange={(e) => setProfile({ ...profile, hashtags: textToList(e.target.value) })} /></label>
        <label>Restrições (o que nunca pode ser dito ou prometido)<textarea rows={3} maxLength={1500} value={profile.restrictions} onChange={(e) => setProfile({ ...profile, restrictions: e.target.value })} /></label>
        <div className="studioRow is-top">
          <label>Posts por semana<input type="number" min={1} max={14} value={profile.posts_per_week} onChange={(e) => setProfile({ ...profile, posts_per_week: Number(e.target.value) })} /></label>
          <fieldset><legend>Formatos</legend>{Object.entries(STUDIO_FORMATS).map(([k, v]) => <label key={k} className="studioCheck">
            <input type="checkbox" checked={profile.formats_enabled.includes(k as StudioFormat)} onChange={(e) => setProfile({ ...profile, formats_enabled: e.target.checked ? [...profile.formats_enabled, k as StudioFormat] : profile.formats_enabled.filter((f) => f !== k) })} />{v}</label>)}</fieldset>
        </div>
        <fieldset><legend>Datas da marca (MM-DD todo ano, ou AAAA-MM-DD)</legend>
          {profile.custom_dates.map((d, idx) => <div key={idx} className="studioDateRow">
            <input aria-label="Data" required pattern="(\d{4}-)?\d{2}-\d{2}" placeholder="11-03" value={d.date} onChange={(e) => setProfile({ ...profile, custom_dates: profile.custom_dates.map((x, i) => (i === idx ? { ...x, date: e.target.value } : x)) })} />
            <input aria-label="Nome da data" required maxLength={80} placeholder="Aniversário da marca" value={d.label} onChange={(e) => setProfile({ ...profile, custom_dates: profile.custom_dates.map((x, i) => (i === idx ? { ...x, label: e.target.value } : x)) })} />
            <button type="button" className="studioLink" aria-label="Remover data" onClick={() => setProfile({ ...profile, custom_dates: profile.custom_dates.filter((_, i) => i !== idx) })}>Remover</button>
          </div>)}
          <button type="button" className="ds-button" onClick={() => setProfile({ ...profile, custom_dates: [...profile.custom_dates, { date: "", label: "" }] })}>+ Data</button>
        </fieldset>
        {error ? <p role="alert">{error}</p> : null}
        <div className="studioActions"><button type="button" className="ds-button" onClick={() => setProfileOpen(false)}>Cancelar</button><button className="ds-button is-primary" disabled={Boolean(busy)}>{busy === "profile-save" ? "Salvando…" : "Salvar perfil"}</button></div>
      </form> : null}
    </Drawer>
  </div></Shell>;
}
