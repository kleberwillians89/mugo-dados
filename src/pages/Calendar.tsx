import { Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent, useEffectEvent } from "react";
import BrandContextPanel from "../components/studio/BrandContextPanel";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  CONTENT_LANGUAGES, STUDIO_CHANNELS, STUDIO_FORMATS, STUDIO_STATUS, type ContentLanguage, createCalendarItem, getPublisher, deleteCalendarItem, getBrandProfile,
  BRAND_PROFILE_SAVED, decideCalendarItem, getCalendar, listToText, localParts, saveBrandProfile, sendForApproval, textToList, toSaoPauloIso, updateCalendarItem,
  basedOnText, confirmSchedule, createContact, listContacts, retryPublish, strategyChat, suggestBrandProfile, getProfileSuggestion, resolveProfileSuggestion, sourcesText,
  type ApprovalCreated, type BasedOn, type ChatTurn, type ClientContact,
  type BrandProfile, type CalendarItem, type PendingProfileSuggestion, type ProfileSuggestionResult, type StudioFormat, type StudioStatus, type WhatsappChannel,
} from "../app/studio";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import Drawer from "../components/Drawer";
import ClientHub from "../components/studio/ClientHub";
import ImportCalendar from "../components/studio/ImportCalendar";
import PostModal from "../components/studio/PostModal";
import MeetingsStrip from "../components/studio/MeetingsStrip";
import ApprovalDelivery from "../components/studio/ApprovalDelivery";
import Approval from "./Approval";
import { DayView, MonthView, WeekView } from "../components/studio/CalendarViews";
import { addDays, draftFrom, fromKey, mondayOf, todayKey, type PostDraft, type ViewMode } from "../app/studioCalendar";
import { getPlan as getMediaPlan, type BoostPost } from "../app/media";
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

export default function Calendar({ canManage, isAgency = false, embedded = false, openProfileRequest = 0, showBrandContext = true }: { canManage: boolean; isAgency?: boolean; embedded?: boolean; openProfileRequest?: number; showBrandContext?: boolean }) {
  // Equipe Mugô: tudo. Cliente: vê o que está com ele/aprovado/publicado, edita texto e data, aprova ou pede ajuste.
  const team = canManage && isAgency;
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const handle = "@" + clientName.toLowerCase().normalize("NFD").replace(/[^a-z0-9]/g, "");
  const isMobile = typeof window !== "undefined" && Boolean(window.matchMedia?.("(max-width: 640px)").matches);
  // /aprovacao (endereço antigo) abre direto o Fluxo de aprovação.
  const [view, setView] = useState<ViewMode>(() => (typeof window !== "undefined" && window.location.pathname.startsWith("/aprovacao") ? "fluxo" : isMobile ? "semana" : "mes"));
  // No celular abre na 1ª semana cheia do próximo mês (a semana do dia 1º costuma ser quase toda do mês anterior).
  const [cursor, setCursor] = useState(() => { const first = firstOfNextMonth(); return isMobile ? addDays(mondayOf(first), mondayOf(first) === first ? 0 : 7) : first; });
  const month = monthOf(cursor);
  const [items, setItems] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [importOpen, setImportOpen] = useState(false);
  const [modal, setModal] = useState<{ item: CalendarItem | null; draft: PostDraft } | null>(null);
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [publisherUrl, setPublisherUrl] = useState<string | null>(null);
  // Business Suite já na Página desta marca; troca junto com a empresa ativa.
  useEffect(() => {
    if (!team) return;
    let alive = true;
    setPublisherUrl(null);
    getPublisher().then((r) => { if (alive) setPublisherUrl(r.url); }).catch(() => undefined);
    return () => { alive = false; };
  }, [team, clientId]);
  const [profileOpen, setProfileOpen] = useState(false);
  const [filter, setFilter] = useState<StudioStatus | "todos">("todos");
  const [copied, setCopied] = useState<string | null>(null);
  const [sending, setSending] = useState<{ selected: string[]; contact_name: string; contact_phone: string; message: string; contact_id: string; send_whatsapp: boolean; notify_team?: boolean } | null>(null);
  const [contacts, setContacts] = useState<{ list: ClientContact[]; channel: WhatsappChannel }>({ list: [], channel: "nao_configurado" });
  const [suggestion, setSuggestion] = useState<(Omit<ProfileSuggestionResult, "profile"> & { pendingId?: string }) | null>(null);
  const [pending, setPending] = useState<PendingProfileSuggestion | null>(null);
  const [chat, setChat] = useState<{ open: boolean; turns: ChatTurn[]; input: string; actions: string[]; basis: BasedOn | null }>({ open: false, turns: [], input: "", actions: [], basis: null });
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
  // Pedido de fora ("abrir perfil da marca"): reage só a um pedido novo, usando o openProfile/team atuais.
  const onProfileRequest = useEffectEvent(() => { if (team) void openProfile(); });
  useEffect(() => { if (openProfileRequest > 0) onProfileRequest(); }, [openProfileRequest]);

  // Plano do Mídia On salvo: as pautas escolhidas para impulsionar ganham data de início no calendário.
  const [boosts, setBoosts] = useState<Record<string, BoostPost>>({});
  useEffect(() => {
    let alive = true;
    Promise.all(months.map((m) => getMediaPlan(m).catch(() => null))).then((plans) => {
      if (!alive) return;
      const map: Record<string, BoostPost> = {};
      for (const p of plans) {
        const strategy = p?.plan?.strategy as { boosts?: { posts?: BoostPost[] } } | undefined;
        for (const b of strategy?.boosts?.posts || []) map[b.item_id] = b;
      }
      setBoosts(map);
    });
    return () => { alive = false; };
  }, [months, clientId]);
  const withBoost = useCallback((i: CalendarItem): CalendarItem => (boosts[i.id] ? { ...i, boost: { start: boosts[i.id].start, end: boosts[i.id].end, budget: boosts[i.id].budget, why: boosts[i.id].why } } : i), [boosts]);
  const visible = useMemo(() => items.filter((i) => filter === "todos" || i.status === filter).map(withBoost), [items, filter, withBoost]);
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
    if (view === "mes" || view === "fluxo") { const d = fromKey(`${month}-01`); d.setMonth(d.getMonth() + direction); setCursor(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`); }
    else setCursor(addDays(cursor, view === "semana" ? 7 * direction : direction));
  }

  const rangeLabel = view === "mes" || view === "fluxo" ? `${MONTH_NAMES[Number(month.slice(5)) - 1]} ${month.slice(0, 4)}`
    : view === "semana" ? (() => { const s = mondayOf(cursor); const e = addDays(s, 6);
      return `${fromKey(s).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "")} – ${fromKey(e).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "")} ${e.slice(0, 4)}`; })()
    : dayLabel(cursor);

  function openItem(item: CalendarItem) { setError(null); setModal({ item: withBoost(item), draft: draftFrom(item) }); }
  function openNew(at: string) {
    setError(null);
    const [date, time] = at.includes("T") ? at.split("T") : [at, "19:00"];
    setModal({ item: null, draft: { date, time, channel: "instagram", format: "reels", pillar: "", title: "", hook: "", caption_draft: "", rationale: "", art_url: "" } });
  }

  async function saveDraft(draft: PostDraft) {
    const body = { scheduled_at: toSaoPauloIso(draft.date, draft.time), channel: draft.channel || "instagram", format: draft.format, pillar: draft.pillar || undefined,
      title: draft.title, hook: draft.hook || undefined, caption_draft: draft.caption_draft || undefined, rationale: draft.rationale || undefined,
      art_url: (draft.art_url || "").trim(),
      // Colaboradores só vão quando mudam (não registra "marcou" a cada salvar).
      ...(JSON.stringify(draft.collaborators || []) !== JSON.stringify(modal?.item?.collaborators || []) ? { collaborators: draft.collaborators || [] } : {}),
      ...(JSON.stringify(draft.product_tags || []) !== JSON.stringify(modal?.item?.product_tags || []) ? { product_tags: draft.product_tags || [] } : {}) };
    // Cliente só manda o que pode mudar (texto e data); o resto fica como a Mugô deixou.
    const clientBody = { scheduled_at: body.scheduled_at, title: body.title, hook: body.hook, caption_draft: body.caption_draft };
    const current = modal?.item;
    const result = await run("save", () => (current ? updateCalendarItem(current.id, team ? body : clientBody) : createCalendarItem(body)), "Não foi possível salvar a pauta.");
    if (!result) return false;
    if (current) { replace(result.item); setModal({ item: withBoost(result.item), draft: draftFrom(result.item) }); } else await load();
    return true;
  }

  async function setStatus(status: StudioStatus, review_note?: string) {
    const current = modal?.item; if (!current) return;
    // Cliente aprova ou pede ajuste pela rota de decisão (basta ver o Calendário); o resto segue a edição normal.
    const decision = !team && (status === "aprovado" || status === "rejeitado");
    const result = await run("status", () => (decision ? decideCalendarItem(current.id, status, review_note || undefined)
      : updateCalendarItem(current.id, { status, ...(review_note !== undefined ? { review_note } : {}) })), "Não foi possível atualizar a pauta.");
    if (result) { replace(result.item); setModal({ item: withBoost(result.item), draft: draftFrom(result.item) }); }
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

  function openSend(only?: string[]) {
    setError(null); setSent(null);
    const selected = only || monthItems.filter((i) => i.status !== "rejeitado" && i.status !== "publicado").map((i) => i.id);
    setSending({ selected, contact_name: "", contact_phone: "", message: "", contact_id: "", send_whatsapp: false, notify_team: true });
    listContacts().then((d) => {
      setContacts({ list: d.contacts, channel: d.whatsapp_channel });
      const main = d.contacts.find((c) => c.is_primary && c.receives.includes("conteudo")) || d.contacts.find((c) => c.receives.includes("conteudo"));
      // Com o WhatsApp da Mugô ligado, o padrão é enviar por ele (contato cadastrado ou digitado na hora).
      setSending((cur) => cur && { ...cur, contact_id: main?.id || "", send_whatsapp: d.whatsapp_channel === "mugozap" });
    }).catch(() => undefined);
  }

  async function submitSend(event: FormEvent) {
    event.preventDefault();
    if (!sending) return;
    // Contato digitado na hora + WhatsApp da Mugô: salva em Aprovação → Contatos e envia por ele.
    const typed = !sending.contact_id && contacts.channel === "mugozap" && sending.send_whatsapp && sending.contact_name.trim() && sending.contact_phone.trim();
    const result = await run("send", async () => {
      let contactId = sending.contact_id;
      const digits = (v: string) => v.replace(/\D/g, "").slice(-11);
      const known = typed ? contacts.list.find((c) => digits(c.phone) === digits(sending.contact_phone)) : undefined;
      if (known) contactId = known.id;
      else if (typed) {
        const saved = (await createContact({ name: sending.contact_name.trim(), phone: sending.contact_phone.trim(), receives: ["conteudo"],
          is_primary: !contacts.list.some((c) => c.is_primary) })).contact;
        contactId = saved.id;
        // Se o envio falhar, a nova tentativa usa o contato já salvo (não duplica).
        setContacts((cur) => ({ ...cur, list: [...cur.list, saved] }));
        setSending((cur) => cur && { ...cur, contact_id: saved.id });
      }
      return sendForApproval({ month, item_ids: sending.selected, message: sending.message || undefined,
      ...(contactId ? { contact_id: contactId, send_whatsapp: sending.send_whatsapp, notify_team: sending.send_whatsapp && sending.notify_team !== false }
        : { contact_name: sending.contact_name || undefined, contact_phone: sending.contact_phone || undefined }) });
    }, "Não foi possível gerar o link de aprovação.");
    if (result) { setSent(result); setSending(null); await load(); }
  }

  async function openProfile() {
    setError(null);
    const data = await run("profile", () => getBrandProfile(), "Não foi possível carregar o perfil da marca.");
    if (data) { setProfile(data.profile); setProfileOpen(true); setSuggestion(null); }
    // Sugestão mensal da IA esperando revisão (só equipe Mugô; falha aqui não atrapalha o perfil).
    setPending(null);
    getProfileSuggestion().then((r) => { if (getActiveClientId() === clientId) setPending(r.suggestion); }).catch(() => undefined);
  }

  function reviewPending() {
    if (!pending) return;
    const { profile: suggested, ...rest } = pending.suggestion;
    setProfile({ ...suggested, custom_dates: profile?.custom_dates || suggested.custom_dates || [],
      content_language: profile?.content_language || suggested.content_language });
    setSuggestion({ ...rest, pendingId: pending.id });
    setPending(null);
  }

  async function dismissPending() {
    if (!pending) return;
    const ok = await run("dismiss", () => resolveProfileSuggestion(pending.id, "descartada"), "Não foi possível descartar a sugestão.");
    if (ok) setPending(null);
  }

  async function suggestProfile() {
    const result = await run("suggest", () => suggestBrandProfile(), "Não foi possível sugerir o perfil.");
    if (result) { const { profile: suggested, ...rest } = result; setProfile((p) => ({ ...suggested, content_language: p?.content_language || suggested.content_language })); setSuggestion(rest); }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const question = chat.input.trim();
    if (!question) return;
    const turns: ChatTurn[] = [...chat.turns, { role: "user", content: question }];
    setChat({ ...chat, turns, input: "" });
    const result = await run("chat", () => strategyChat(month, turns), "O Head de Estratégia não respondeu agora.");
    setChat((c) => ({ ...c, turns: result ? [...turns, { role: "assistant", content: result.reply }] : turns,
      actions: result?.suggested_actions || c.actions, basis: result?.based_on || c.basis }));
  }

  async function submitProfile(event: FormEvent) {
    event.preventDefault();
    if (!profile) return;
    const result = await run("profile-save", () => saveBrandProfile(profile), "Não foi possível salvar o perfil.");
    if (result) {
      if (suggestion?.pendingId) await resolveProfileSuggestion(suggestion.pendingId, "aplicada").catch(() => undefined);
      setProfile(result.profile); setProfileOpen(false); setSuggestion(null);
      // A Matriz (outra aba da mesma página) fica montada: avisa que o perfil mudou para ela reler.
      window.dispatchEvent(new CustomEvent(BRAND_PROFILE_SAVED, { detail: result.profile }));
    }
  }

  const common = { items: visible, canManage, canCreate: team, onOpen: openItem, onMove: (i: CalendarItem, d: string) => void move(i, d), onCreate: openNew };

  const content = <div className={embedded ? "studioEmbeddedPage" : "ds-page studioPage"}>
    <PageHeader company={clientName} title="Calendário editorial" controls={team ? <div className="studioControls">
      <button type="button" className="ds-button" onClick={() => void openProfile()} disabled={Boolean(busy)}>Perfil da marca</button>
      <button type="button" className="ds-button" onClick={() => setImportOpen(true)} disabled={Boolean(busy)}>Importar calendário</button>
      <button type="button" className="ds-button" onClick={() => { setError(null); setChat((c) => ({ ...c, open: true })); }} disabled={Boolean(busy)}>Estratégia (IA)</button>
      <button type="button" className="ds-button" onClick={() => openNew(view === "dia" ? cursor : `${month}-01`)} disabled={Boolean(busy)}>+ Pauta</button>
      <button type="button" className="ds-button" onClick={() => openSend()} disabled={Boolean(busy) || !monthItems.some((i) => i.status !== "rejeitado")}>Enviar ao cliente</button>
    </div> : undefined} />
    {team && showBrandContext ? <BrandContextPanel clientId={clientId} /> : null}
    <div className="calToolbar">
      <div className="calNav">
        <button type="button" className="ds-button" aria-label="Anterior" onClick={() => step(-1)}>‹</button>
        <button type="button" className="ds-button" onClick={() => setCursor(todayKey())}>Hoje</button>
        <button type="button" className="ds-button" aria-label="Próximo" onClick={() => step(1)}>›</button>
        <h2 className="calRange">{rangeLabel.charAt(0).toUpperCase() + rangeLabel.slice(1)}</h2>
      </div>
      <div className="studioTabs" role="tablist" aria-label="Visão">
        {(["mes", "semana", "dia", "fluxo"] as const).map((v) => <button key={v} role="tab" aria-selected={view === v} className={view === v ? "is-active" : ""} onClick={() => setView(v)}>{v === "mes" ? "Mês" : v === "semana" ? "Semana" : v === "dia" ? "Dia" : "Fluxo de aprovação"}</button>)}
      </div>
    </div>
    {view !== "fluxo" ? <div className="studioTabs calStatus" role="tablist" aria-label="Filtrar por status">
      {(["todos", "rascunho", "em_revisao", "aprovado", "rejeitado", "publicado"] as const).filter((key) => isAgency || key !== "rascunho").map((key) => (
        <button key={key} role="tab" aria-selected={filter === key} className={`${filter === key ? "is-active" : ""} is-${key}`} onClick={() => setFilter(key)}>
          {key === "todos" ? "Todos" : STUDIO_STATUS[key]} <span>{counts[key] || 0}</span>
        </button>
      ))}
    </div> : null}
    {error && !modal ? <p role="alert" className="studioError">{error}</p> : null}
    {notes.length ? <ul className="studioNotes">{notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
    {loading && !items.length ? <p>Carregando calendário…</p> : null}
    <ClientHub team={team} canManage={canManage} isAgency={isAgency} month={month}
      posts={monthItems.map((i) => ({ id: i.id, title: i.title || "Post sem título", status: i.status }))}
      onOpenItem={(id) => { const it = items.find((i) => i.id === id); if (it) openItem(it); }} onChanged={() => void load()} />
    {!loading && !monthItems.length && !error && view === "mes" ? <div className="studioEmpty is-slim"><p>{team ? "Nenhuma pauta neste mês." : "Nenhum post para você neste mês ainda. Quando a Mugô mandar conteúdo para aprovar, ele aparece aqui."}</p>{team ? <p> crie o conteúdo na <b>Matriz</b> e envie para cá, ou use o <b>+</b> de um dia.</p> : null}</div> : null}

    {view === "mes" ? <MonthView month={month} {...common} onPickDay={(d) => { setCursor(d); setView("dia"); }} /> : null}
    {view === "semana" ? <WeekView weekStart={mondayOf(cursor)} {...common} onPickDay={(d) => { setCursor(d); setView("dia"); }} /> : null}
    <MeetingsStrip month={month} clientId={clientId} />
    {view === "dia" ? <DayView day={cursor} {...common} /> : null}
    {view === "fluxo" ? <Approval embedded month={month} tabs={["funil"]} canManage={canManage} isAgency={isAgency}
      onOpenItem={(id) => { const it = items.find((i) => i.id === id); if (it) openItem(it); }} onChanged={() => void load()} /> : null}


    {modal ? <PostModal key={modal.item ? `${modal.item.id}:${modal.item.updated_at || ""}:${modal.item.status}` : "new"} item={modal.item} initial={modal.draft} handle={handle} pillars={(profile?.pillars || []).map((p) => p.name)}
      canManage={canManage} clientMode={!isAgency} busy={Boolean(busy)} error={error} onClose={() => setModal(null)} onSave={saveDraft} onStatus={setStatus} onDelete={removeCurrent}
      publisherUrl={publisherUrl || undefined}
      onItemChange={team ? (next) => { replace(next); setModal((m) => (m ? { item: next, draft: draftFrom(next) } : m)); } : undefined}
      onSendForApproval={team && modal.item ? () => { const id = modal.item!.id; setModal(null); openSend([id]); } : undefined}
      onConfirmSchedule={team && modal.item ? async (now?: boolean) => {
        const out = await run("schedule", () => confirmSchedule(modal.item!.id, Boolean(now)), now ? "Não foi possível publicar agora." : "Não foi possível agendar.");
        if (out) { replace(out.item); setModal((m) => m && { ...m, item: out.item }); }
      } : undefined}
      onRetryPublish={team && modal.item ? async () => {
        const out = await run("publish", () => retryPublish(modal.item!.id), "Não foi possível liberar a publicação.");
        if (out) { replace(out.item); setModal((m) => m && { ...m, item: out.item }); }
      } : undefined} /> : null}

    <Drawer open={Boolean(sending)} title="Enviar ao cliente" description="Gera um link sem login para o cliente aprovar ou pedir ajuste. Válido por 14 dias." width="lg" onClose={() => { if (!busy) setSending(null); }}>
      {sending ? <form className="studioForm" onSubmit={submitSend}>
        <fieldset><legend>Pautas ({sending.selected.length})</legend>
          {monthItems.filter((i) => i.status !== "rejeitado").map((i) => <label key={i.id} className="studioCheck">
            <input type="checkbox" checked={sending.selected.includes(i.id)} onChange={(e) => setSending({ ...sending, selected: e.target.checked ? [...sending.selected, i.id] : sending.selected.filter((x) => x !== i.id) })} />
            {localParts(i.scheduled_at).label} · {i.title}</label>)}
        </fieldset>
        {contacts.list.length ? <label>Quem aprova<select value={sending.contact_id} onChange={(e) => setSending({ ...sending, contact_id: e.target.value })}>
          {contacts.list.map((c) => <option key={c.id} value={c.id}>{c.name}{c.role ? ` · ${c.role}` : ""}{c.is_primary ? " (principal)" : ""}</option>)}
          <option value="">Outra pessoa…</option></select></label> : <p className="postArtHint">{contacts.channel === "mugozap" ? "Digite quem aprova: a pessoa fica salva em Aprovação → Contatos para os próximos envios."
            : <>Dica: cadastre quem aprova em <b>Aprovação → Contatos</b> para enviar pelo WhatsApp da Mugô.</>}</p>}
        {!sending.contact_id ? <div className="studioRow">
          <label>Nome do contato<input maxLength={120} value={sending.contact_name} onChange={(e) => setSending({ ...sending, contact_name: e.target.value })} placeholder="Ana" /></label>
          <label>WhatsApp<input inputMode="tel" maxLength={30} value={sending.contact_phone} onChange={(e) => setSending({ ...sending, contact_phone: e.target.value })} placeholder="(11) 98888-7777" /></label>
        </div> : null}
        {contacts.channel === "mugozap" ? <label className="studioCheck"><input type="checkbox" checked={sending.send_whatsapp}
          onChange={(e) => setSending({ ...sending, send_whatsapp: e.target.checked })} />Enviar agora pelo WhatsApp oficial da Mugô (template com a arte){sending.contact_id ? "" : " e salvar a pessoa em Aprovação → Contatos"}</label> : null}
        {contacts.channel === "mugozap" && sending.send_whatsapp ? <label className="studioCheck"><input type="checkbox" checked={sending.notify_team !== false}
          onChange={(e) => setSending({ ...sending, notify_team: e.target.checked })} />Enviar cópia para a equipe Mugô (mesmo link, todos na mesma página)</label> : null}
        <label>Mensagem (opcional; sem ela usamos uma padrão)<textarea rows={3} maxLength={1000} value={sending.message} onChange={(e) => setSending({ ...sending, message: e.target.value })} /></label>
        {error ? <p role="alert">{error}</p> : null}
        <div className="studioActions"><button type="button" className="ds-button" onClick={() => setSending(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy) || !sending.selected.length}>{busy === "send" ? "Gerando…" : "Gerar link"}</button></div>
      </form> : null}
    </Drawer>

    <Drawer open={Boolean(sent)} title="Link de aprovação pronto" onClose={() => setSent(null)}>
      {sent ? <div className="studioForm">
        <p>As pautas foram para <b>Em revisão</b> e voltam aprovadas ou com o pedido de ajuste do cliente.</p>
        {sent.whatsapp?.status === "enviado" ? <p className="studioOk">✓ Enviado pelo WhatsApp da Mugô.</p> : null}
        {sent.whatsapp?.status === "falhou" ? <p role="alert" className="studioError">WhatsApp da Mugô: {"detail" in sent.whatsapp ? sent.whatsapp.detail : ""} Use os botões abaixo.</p> : null}
        {sent.whatsapp?.status === "enviado" || sent.team?.length ? <ApprovalDelivery sent={sent} /> : null}
        <label>Link<input readOnly value={sent.link} onFocus={(e) => e.currentTarget.select()} /></label>
        <div className="studioActions">
          {contacts.channel === "wa_link" ? <a className="ds-button is-primary" href={sent.whatsapp_url} target="_blank" rel="noreferrer noopener">Abrir no WhatsApp</a> : null}
          <button type="button" className="ds-button" onClick={() => void navigator.clipboard.writeText(sent.whatsapp_text).then(() => setCopied("link"), () => undefined)}>{copied === "link" ? "Mensagem copiada ✓" : "Copiar mensagem"}</button>
        </div>
      </div> : null}
    </Drawer>

    <Drawer open={chat.open} title="Head de Estratégia" description={`Converse sobre ${MONTH_NAMES[Number(month.slice(5)) - 1]} com o calendário e os dados da conta.`} width="lg" onClose={() => { if (busy !== "chat") setChat((c) => ({ ...c, open: false })); }}>
      <div className="aiChat">
        {!chat.turns.length ? <div className="aiChatEmpty"><p>Exemplos:</p>
          {["O que está faltando no calendário deste mês?", "Quais pautas puxam as vendas das campanhas que mais venderam?", "Como equilibrar os pilares nas próximas semanas?"].map((q) =>
            <button key={q} type="button" className="studioLink" onClick={() => setChat((c) => ({ ...c, input: q }))}>{q}</button>)}</div> : null}
        {chat.turns.map((t, n) => <div key={n} className={`aiTurn is-${t.role}`}>{t.content}</div>)}
        {busy === "chat" ? <div className="aiTurn is-assistant">Pensando…</div> : null}
        {chat.basis ? <p className="aiBasis">{basedOnText(chat.basis)}</p> : null}
        {chat.actions.length ? <ul className="aiList">{chat.actions.map((a) => <li key={a}>→ {a}</li>)}</ul> : null}
        {error && chat.open ? <p role="alert" className="studioError">{error}</p> : null}
        <form className="aiChatForm" onSubmit={ask}>
          <textarea rows={2} maxLength={2000} value={chat.input} placeholder="Pergunte sobre o mês, pilares, datas, campanhas…" onChange={(e) => setChat({ ...chat, input: e.target.value })}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); (e.currentTarget.form as HTMLFormElement | null)?.requestSubmit(); } }} />
          <button className="ds-button is-primary" disabled={busy === "chat" || !chat.input.trim()}>Enviar</button>
        </form>
      </div>
    </Drawer>

    {team ? <ImportCalendar open={importOpen} onClose={() => setImportOpen(false)}
      onDone={(summary) => { setImportOpen(false); setNotes([summary]); void load(); }} /> : null}

    <Drawer open={profileOpen} title="Perfil da marca" description="Base para a IA escrever no jeito da marca." width="lg" onClose={() => { if (!busy) setProfileOpen(false); }}>
      {profile ? <form className="studioForm" onSubmit={submitProfile}>
        <div className="aiBrand">
          <strong><Sparkles className="uiGlyph" size={14} aria-hidden="true" /> Brand Manager (IA)</strong>
          <p>Lê 12 meses da conta: posts mais curtidos e mais salvos (texto e imagem), o que o cliente aprovou, pediu para ajustar, comentou e reescreveu, a Mídia On e as vendas. Palavras proibidas e restrições cadastradas pela equipe nunca são apagadas. Nada é salvo antes de você revisar.</p>
          {pending ? <div className="aiPending" role="status">
            <span>Sugestão de {pending.month.split("-").reverse().join("/")} pronta para revisar.</span>
            <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={reviewPending}>Ver sugestão</button>
            <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => void dismissPending()}>Descartar</button>
          </div> : null}
          <div className="studioRow">
            <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void suggestProfile()}>{busy === "suggest" ? "Analisando 12 meses… (até 2 min)" : "Sugerir perfil com IA"}</button>
          </div>
          {suggestion ? <div className="aiResult">
            <p className="aiBasis">{sourcesText(suggestion.sources) || basedOnText(suggestion.based_on)}</p>
            {suggestion.reasons?.length ? <ul className="aiReasons">{suggestion.reasons.map((r) => <li key={r.campo + r.motivo}><b>{r.campo}:</b> {r.motivo}</li>)}</ul> : null}
            <ul className="aiList">{suggestion.notes.map((n) => <li key={n}>{n}</li>)}</ul>
            <p className="aiWhy">Revise os campos abaixo e clique em <b>Salvar perfil</b>.</p></div> : null}
        </div>
        <label>Idioma das publicações e das respostas de comentário
          <select value={profile.content_language || "pt-BR"} onChange={(e) => setProfile({ ...profile, content_language: e.target.value as ContentLanguage })}>
            {Object.entries(CONTENT_LANGUAGES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </select>
          {profile.content_language && profile.content_language !== "pt-BR"
            ? <small className="libHint">Legendas, roteiros, hashtags e respostas saem em {CONTENT_LANGUAGES[profile.content_language].toLowerCase()}. Pautas e justificativas continuam em português para a equipe.</small> : null}
        </label>
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
        <label>Identidade visual (cores, composição, estilo de foto e de arte)<textarea rows={3} maxLength={1500} value={profile.visual_identity || ""} placeholder="A IA preenche olhando as imagens dos posts mais curtidos." onChange={(e) => setProfile({ ...profile, visual_identity: e.target.value })} /></label>
        <div className="studioRow is-top">
          <label>Posts por semana<input type="number" min={1} max={14} value={profile.posts_per_week} onChange={(e) => setProfile({ ...profile, posts_per_week: Number(e.target.value) })} /></label>
          <fieldset><legend>Formatos</legend>{Object.entries(STUDIO_FORMATS).map(([k, v]) => <label key={k} className="studioCheck">
            <input type="checkbox" checked={profile.formats_enabled.includes(k as StudioFormat)} onChange={(e) => setProfile({ ...profile, formats_enabled: e.target.checked ? [...profile.formats_enabled, k as StudioFormat] : profile.formats_enabled.filter((f) => f !== k) })} />{v}</label>)}</fieldset>
        </div>
        <fieldset><legend>Plataformas do planejamento editorial</legend>
          <p className="libHint">Independem das contas conectadas. Sem frequência específica, o total semanal é distribuído entre as redes conforme a estratégia.</p>
          {Object.entries(STUDIO_CHANNELS).map(([key, label]) => {
            const channel = key as keyof typeof STUDIO_CHANNELS;
            const selected = (profile.editorial_platforms || []).includes(channel);
            const frequencies = profile.posts_per_week_by_platform || {};
            return <div key={channel} className="studioRow">
              <label className="studioCheck"><input type="checkbox" checked={selected} onChange={(e) => {
                const editorial_platforms = e.target.checked
                  ? [...(profile.editorial_platforms || []), channel]
                  : (profile.editorial_platforms || []).filter((item) => item !== channel);
                const posts_per_week_by_platform = { ...frequencies };
                if (!e.target.checked) delete posts_per_week_by_platform[channel];
                setProfile({ ...profile, editorial_platforms, posts_per_week_by_platform });
              }} />{label}</label>
              {selected ? <label>Posts/semana nesta rede (opcional)<input type="number" min={1} max={14}
                value={frequencies[channel] ?? ""} placeholder="Distribuição automática" onChange={(e) => {
                  const posts_per_week_by_platform = { ...frequencies };
                  if (e.target.value) posts_per_week_by_platform[channel] = Number(e.target.value); else delete posts_per_week_by_platform[channel];
                  setProfile({ ...profile, posts_per_week_by_platform });
                }} /></label> : null}
            </div>;
          })}
        </fieldset>
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
  </div>;
  return embedded ? content : <Shell title="Calendário" variant="editorial">{content}</Shell>;
}
