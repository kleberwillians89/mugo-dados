import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  STUDIO_FORMATS, STUDIO_STATUS, createCalendarItem, deleteCalendarItem, generateCalendar, getBrandProfile,
  getCalendar, listToText, localParts, saveBrandProfile, sendForApproval, textToList, toSaoPauloIso, updateCalendarItem,
  type ApprovalCreated,
  type BrandProfile, type CalendarItem, type StudioFormat, type StudioStatus,
} from "../app/studio";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import Drawer from "../components/Drawer";
import PostModal from "../components/studio/PostModal";
import { DayView, MonthView, WeekView } from "../components/studio/CalendarViews";
import { addDays, draftFrom, fromKey, mondayOf, todayKey, type PostDraft, type ViewMode } from "../app/studioCalendar";
import { setItemAssets, type StudioAsset } from "../app/studioAssets";
import "../styles/studio.css";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const monthOf = (dayKey: string) => dayKey.slice(0, 7);
const MONTH_NAMES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const dayLabel = (key: string) => fromKey(key).toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });

function firstOfNextMonth() {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() + 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

export default function Calendar({ canManage }: { canManage: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const handle = "@" + clientName.toLowerCase().normalize("NFD").replace(/[^a-z0-9]/g, "");
  const isMobile = typeof window !== "undefined" && Boolean(window.matchMedia?.("(max-width: 640px)").matches);
  const [view, setView] = useState<ViewMode>(isMobile ? "semana" : "mes");
  // No celular abre na 1ª semana cheia do próximo mês (a semana do dia 1º costuma ser quase toda do mês anterior).
  const [cursor, setCursor] = useState(() => { const first = firstOfNextMonth(); return isMobile ? addDays(mondayOf(first), mondayOf(first) === first ? 0 : 7) : first; });
  const month = monthOf(cursor);
  const [items, setItems] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [modal, setModal] = useState<{ item: CalendarItem | null; draft: PostDraft } | null>(null);
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [filter, setFilter] = useState<StudioStatus | "todos">("todos");
  const [copied, setCopied] = useState<string | null>(null);
  const [sending, setSending] = useState<{ selected: string[]; contact_name: string; contact_phone: string; message: string } | null>(null);
  const [sent, setSent] = useState<ApprovalCreated | null>(null);

  // Meses que a visão atual toca (a semana pode atravessar dois meses).
  const months = useMemo(() => {
    if (view === "semana") { const start = mondayOf(cursor); return [...new Set([monthOf(start), monthOf(addDays(start, 6))])]; }
    return [month];
  }, [view, cursor, month]);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const results = await Promise.all(months.map((m) => getCalendar(m)));
      if (getActiveClientId() === clientId) setItems([...new Map(results.flatMap((r) => r.items).map((i) => [i.id, i])).values()]);
    } catch (cause) { setError(message(cause, "Não foi possível carregar o calendário.")); }
    finally { setLoading(false); }
  }, [months, clientId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { getBrandProfile().then((d) => setProfile(d.profile)).catch(() => undefined); }, [clientId]);

  const visible = useMemo(() => items.filter((i) => filter === "todos" || i.status === filter), [items, filter]);
  const monthItems = useMemo(() => items.filter((i) => i.month.startsWith(month)), [items, month]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { todos: monthItems.length };
    for (const item of monthItems) c[item.status] = (c[item.status] || 0) + 1;
    return c;
  }, [monthItems]);

  async function run<T>(key: string, fn: () => Promise<T>, fallback: string) {
    if (busy || getActiveClientId() !== clientId) return null;
    setBusy(key); setError(null);
    try { return await fn(); }
    catch (cause) { setError(message(cause, fallback)); return null; }
    finally { setBusy(null); }
  }

  const replace = (item: CalendarItem) => setItems((all) => all.map((i) => (i.id === item.id ? item : i)));

  function step(direction: -1 | 1) {
    if (view === "mes") { const d = fromKey(`${month}-01`); d.setMonth(d.getMonth() + direction); setCursor(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`); }
    else setCursor(addDays(cursor, view === "semana" ? 7 * direction : direction));
  }

  const rangeLabel = view === "mes" ? `${MONTH_NAMES[Number(month.slice(5)) - 1]} ${month.slice(0, 4)}`
    : view === "semana" ? (() => { const s = mondayOf(cursor); const e = addDays(s, 6);
      return `${fromKey(s).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "")} – ${fromKey(e).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "")} ${e.slice(0, 4)}`; })()
    : dayLabel(cursor);

  async function generate() {
    if (monthItems.some((i) => i.origin === "ia" && i.status === "rascunho") &&
      !window.confirm(`Os rascunhos da IA de ${MONTH_NAMES[Number(month.slice(5)) - 1]} serão substituídos. Itens aprovados, em revisão ou criados à mão ficam. Continuar?`)) return;
    const result = await run("generate", () => generateCalendar(month), "Não foi possível gerar o calendário.");
    if (result) { setNotes(result.observacoes || []); await load(); }
  }

  function openItem(item: CalendarItem) { setError(null); setModal({ item, draft: draftFrom(item) }); }
  function openNew(at: string) {
    setError(null);
    const [date, time] = at.includes("T") ? at.split("T") : [at, "19:00"];
    setModal({ item: null, draft: { date, time, format: "reels", pillar: "", title: "", hook: "", caption_draft: "", rationale: "" } });
  }

  async function saveDraft(draft: PostDraft) {
    const body = { scheduled_at: toSaoPauloIso(draft.date, draft.time), format: draft.format, pillar: draft.pillar || undefined,
      title: draft.title, hook: draft.hook || undefined, caption_draft: draft.caption_draft || undefined, rationale: draft.rationale || undefined };
    const current = modal?.item;
    const result = await run("save", () => (current ? updateCalendarItem(current.id, body) : createCalendarItem(body)), "Não foi possível salvar a pauta.");
    if (!result) return false;
    if (current) { replace(result.item); setModal({ item: result.item, draft: draftFrom(result.item) }); } else await load();
    return true;
  }

  async function setStatus(status: StudioStatus, review_note?: string) {
    const current = modal?.item; if (!current) return;
    const result = await run("status", () => updateCalendarItem(current.id, { status, ...(review_note !== undefined ? { review_note } : {}) }), "Não foi possível atualizar a pauta.");
    if (result) { replace(result.item); setModal({ item: result.item, draft: draftFrom(result.item) }); }
  }

  async function saveAssets(assets: StudioAsset[]) {
    const current = modal?.item; if (!current) return false;
    const result = await run("assets", () => setItemAssets(current.id, assets.map((a) => a.id)), "Não foi possível salvar a arte da pauta.");
    if (!result) return false;
    const item = { ...current, assets: result.assets };
    replace(item); setModal((m) => (m && m.item?.id === item.id ? { ...m, item } : m));
    return true;
  }

  async function removeCurrent() {
    const current = modal?.item; if (!current || !window.confirm(`Excluir a pauta “${current.title}”?`)) return;
    const ok = await run("delete", () => deleteCalendarItem(current.id), "Não foi possível excluir a pauta.");
    if (ok) { setItems((all) => all.filter((i) => i.id !== current.id)); setModal(null); }
  }

  async function move(item: CalendarItem, dayKey: string) {
    const { time } = localParts(item.scheduled_at);
    const result = await run("move", () => updateCalendarItem(item.id, { scheduled_at: toSaoPauloIso(dayKey, time) }), "Não foi possível mudar o dia da pauta.");
    if (result) { if (monthOf(dayKey) === month || view !== "mes") replace(result.item); else setItems((all) => all.filter((i) => i.id !== item.id)); }
  }

  function openSend() {
    setError(null); setSent(null);
    setSending({ selected: monthItems.filter((i) => i.status !== "rejeitado").map((i) => i.id), contact_name: "", contact_phone: "", message: "" });
  }

  async function submitSend(event: FormEvent) {
    event.preventDefault();
    if (!sending) return;
    const result = await run("send", () => sendForApproval({ month, item_ids: sending.selected, contact_name: sending.contact_name || undefined,
      contact_phone: sending.contact_phone || undefined, message: sending.message || undefined }), "Não foi possível gerar o link de aprovação.");
    if (result) { setSent(result); setSending(null); await load(); }
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

  const common = { items: visible, canManage, onOpen: openItem, onMove: (i: CalendarItem, d: string) => void move(i, d), onCreate: openNew };

  return <Shell title="Calendário" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Calendário editorial" controls={canManage ? <div className="studioControls">
      <button type="button" className="ds-button" onClick={() => void openProfile()} disabled={Boolean(busy)}>Perfil da marca</button>
      <button type="button" className="ds-button" onClick={() => openNew(view === "dia" ? cursor : `${month}-01`)} disabled={Boolean(busy)}>+ Pauta</button>
      <button type="button" className="ds-button" onClick={openSend} disabled={Boolean(busy) || !monthItems.some((i) => i.status !== "rejeitado")}>Enviar ao cliente</button>
      <button type="button" className="ds-button is-primary" onClick={() => void generate()} disabled={Boolean(busy)}>{busy === "generate" ? "Gerando… (até 1 min)" : `Gerar ${MONTH_NAMES[Number(month.slice(5)) - 1]} com IA`}</button>
    </div> : undefined} />
    <div className="calToolbar">
      <div className="calNav">
        <button type="button" className="ds-button" aria-label="Anterior" onClick={() => step(-1)}>‹</button>
        <button type="button" className="ds-button" onClick={() => setCursor(todayKey())}>Hoje</button>
        <button type="button" className="ds-button" aria-label="Próximo" onClick={() => step(1)}>›</button>
        <h2 className="calRange">{rangeLabel.charAt(0).toUpperCase() + rangeLabel.slice(1)}</h2>
      </div>
      <div className="studioTabs" role="tablist" aria-label="Visão">
        {(["mes", "semana", "dia"] as const).map((v) => <button key={v} role="tab" aria-selected={view === v} className={view === v ? "is-active" : ""} onClick={() => setView(v)}>{v === "mes" ? "Mês" : v === "semana" ? "Semana" : "Dia"}</button>)}
      </div>
    </div>
    <div className="studioTabs calStatus" role="tablist" aria-label="Filtrar por status">
      {(["todos", "rascunho", "em_revisao", "aprovado", "rejeitado"] as const).map((key) => (
        <button key={key} role="tab" aria-selected={filter === key} className={`${filter === key ? "is-active" : ""} is-${key}`} onClick={() => setFilter(key)}>
          {key === "todos" ? "Todos" : STUDIO_STATUS[key]} <span>{counts[key] || 0}</span>
        </button>
      ))}
    </div>
    {error && !modal ? <p role="alert" className="studioError">{error}</p> : null}
    {notes.length ? <ul className="studioNotes">{notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
    {loading && !items.length ? <p>Carregando calendário…</p> : null}
    {!loading && !monthItems.length && !error && view === "mes" ? <div className="studioEmpty"><p>Nenhuma pauta neste mês.</p>{canManage ? <p>Preencha o <b>perfil da marca</b> e clique em <b>Gerar com IA</b>, ou use o <b>+</b> de um dia.</p> : null}</div> : null}

    {view === "mes" ? <MonthView month={month} {...common} onPickDay={(d) => { setCursor(d); setView("dia"); }} /> : null}
    {view === "semana" ? <WeekView weekStart={mondayOf(cursor)} {...common} onPickDay={(d) => { setCursor(d); setView("dia"); }} /> : null}
    {view === "dia" ? <DayView day={cursor} {...common} /> : null}

    {modal ? <PostModal key={modal.item ? `${modal.item.id}:${modal.item.updated_at || ""}:${modal.item.status}` : "new"} item={modal.item} initial={modal.draft} handle={handle} pillars={(profile?.pillars || []).map((p) => p.name)}
      canManage={canManage} busy={Boolean(busy)} error={error} onClose={() => setModal(null)} onSave={saveDraft} onStatus={setStatus} onDelete={removeCurrent} onAssets={saveAssets} /> : null}

    <Drawer open={Boolean(sending)} title="Enviar ao cliente" description="Gera um link sem login para o cliente aprovar ou pedir ajuste. Válido por 14 dias." width="lg" onClose={() => { if (!busy) setSending(null); }}>
      {sending ? <form className="studioForm" onSubmit={submitSend}>
        <fieldset><legend>Pautas ({sending.selected.length})</legend>
          {monthItems.filter((i) => i.status !== "rejeitado").map((i) => <label key={i.id} className="studioCheck">
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
