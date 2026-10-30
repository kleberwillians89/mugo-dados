import { useCallback, useEffect, useState, type DragEvent, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  MESSAGE_KINDS, RECEIVES, STAGES, STAGE_STATUS, STUDIO_FORMATS, cancelApproval, createContact, deleteContact, getPipeline,
  listApprovals, listContacts, listMessages, localParts, previewMessage, sendMessage, updateCalendarItem, updateContact,
  type ApprovalRequest, type ClientContact, type ContactInput, type MessageKind, type MessageLog, type MessagePreview,
  type MessageResult, type PipelineItem, type Receives, type Stage,
} from "../app/studio";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import Drawer from "../components/Drawer";
import { navigateToAppRoute } from "../app/routes";
import "../styles/studio.css";

type Tab = "funil" | "pedidos" | "contatos" | "mensagens";
const TABS: Record<Tab, string> = { funil: "Funil", pedidos: "Pedidos", contatos: "Contatos", mensagens: "Mensagens" };
const MONTH_NAMES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const REQUEST_STATUS: Record<ApprovalRequest["status"], string> = { aberto: "Aguardando cliente", concluido: "Respondido", cancelado: "Cancelado", expirado: "Expirado" };
const EDITABLE_LABEL: Record<string, string> = { destaque: "Destaque / aprendizado", atencao: "Ponto de atenção", proximo: "Próximo passo" };
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const thisMonth = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const shiftMonth = (m: string, n: number) => { const d = new Date(Number(m.slice(0, 4)), Number(m.slice(5)) - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const dateTime = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const emptyContact: ContactInput = { name: "", phone: "", role: "", receives: ["conteudo"], is_primary: false };

/** Aprovação de conteúdo: o "Comercial" do CRM virado funil de pautas + WhatsApp da Mugô. */
export default function Approval({ canManage }: { canManage: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const [tab, setTab] = useState<Tab>("funil");
  const [month, setMonth] = useState(thisMonth);
  const [items, setItems] = useState<PipelineItem[]>([]);
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [contacts, setContacts] = useState<ClientContact[]>([]);
  const [channel, setChannel] = useState<"mugozap" | "wa_link">("wa_link");
  const [messages, setMessages] = useState<MessageLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState<Stage | null>(null);
  const [editing, setEditing] = useState<{ id: string | null; data: ContactInput } | null>(null);
  const [compose, setCompose] = useState<{ kind: MessageKind; contact_id: string; request_id?: string; preview: MessagePreview | null; overrides: Record<string, string> } | null>(null);
  const [result, setResult] = useState<MessageResult | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [pipe, reqs, cts, msgs] = await Promise.all([getPipeline(month), listApprovals(), listContacts(), listMessages()]);
      if (getActiveClientId() !== clientId) return;
      setItems(pipe.items || []); setRequests(reqs.requests || []); setContacts(cts.contacts || []);
      setChannel(cts.whatsapp_channel === "mugozap" ? "mugozap" : "wa_link"); setMessages(msgs.messages || []);
    } catch (cause) { setError(message(cause, "Não foi possível carregar a aprovação.")); }
    finally { setLoading(false); }
  }, [month, clientId]);
  useEffect(() => { void load(); }, [load]);

  async function run<T>(key: string, fn: () => Promise<T>, fallback: string) {
    if (busy) return null;
    setBusy(key); setError(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }

  async function moveTo(item: PipelineItem, stage: Stage) {
    if (stage === item.stage || !canManage) return;
    if (stage === "com_cliente") { setError("Para mandar ao cliente, use “Enviar ao cliente” no Calendário: o link vai junto."); return; }
    const status = STAGE_STATUS[stage]!;
    const note = status === "rejeitado" ? window.prompt("O que precisa mudar?") : undefined;
    if (status === "rejeitado" && !note) return;
    const ok = await run("move", () => updateCalendarItem(item.id, { status, ...(note ? { review_note: note } : {}) }), "Não foi possível mover a pauta.");
    if (ok) await load();
  }

  function onDrop(e: DragEvent, stage: Stage) {
    e.preventDefault(); setOver(null);
    const item = items.find((i) => i.id === e.dataTransfer.getData("text/plain"));
    if (item) void moveTo(item, stage);
  }

  async function openCompose(kind: MessageKind, request_id?: string) {
    setResult(null); setError(null);
    const wants: Receives = kind === "trafego" || kind === "semanal" ? "trafego" : kind === "resultados" ? "resultados" : "conteudo";
    const contact = contacts.find((c) => c.is_primary && c.receives.includes(wants)) || contacts.find((c) => c.receives.includes(wants));
    const draft = { kind, contact_id: contact?.id || "", request_id, preview: null, overrides: {} };
    setCompose(draft);
    if (contact) await refreshPreview(draft);
  }

  async function refreshPreview(draft: NonNullable<typeof compose>) {
    const preview = await run("preview", () => previewMessage({ kind: draft.kind, contact_id: draft.contact_id || undefined, request_id: draft.request_id, overrides: draft.overrides }), "Não foi possível montar a mensagem.");
    setCompose({ ...draft, preview: preview || null, overrides: preview ? Object.fromEntries(preview.editable.map((k) => [k, draft.overrides[k] ?? preview.params[k]])) : draft.overrides });
  }

  async function submitMessage() {
    if (!compose) return;
    const sent = await run("send", () => sendMessage({ kind: compose.kind, contact_id: compose.contact_id || undefined, request_id: compose.request_id, overrides: compose.overrides }), "Não foi possível enviar.");
    if (sent) { setResult(sent); setCompose(null); if (sent.whatsapp_url) window.open(sent.whatsapp_url, "_blank", "noopener"); await load(); }
  }

  async function saveContact(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const data = { ...editing.data, role: editing.data.role || undefined };
    const ok = await run("contact", () => (editing.id ? updateContact(editing.id, data) : createContact(data)), "Não foi possível salvar o contato.");
    if (ok) { setEditing(null); await load(); }
  }

  const byStage = (stage: Stage) => items.filter((i) => i.stage === stage);
  const pendingClient = items.filter((i) => i.stage === "com_cliente").length;

  return <Shell title="Aprovação" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Aprovação de conteúdo" controls={canManage ? <div className="studioControls">
      <button type="button" className="ds-button" onClick={() => navigateToAppRoute("calendar")}>Calendário</button>
      <button type="button" className="ds-button is-primary" onClick={() => { setTab("mensagens"); void openCompose("agenda"); }} disabled={!contacts.length}>Nova mensagem</button>
    </div> : undefined} />
    <p className="libHint">WhatsApp: {channel === "mugozap" ? "envio pelo canal oficial da Mugô (MugôZap)." : "MugôZap ainda não configurado no Dados; as mensagens abrem no WhatsApp para envio manual."}</p>

    <div className="studioTabs" role="tablist" aria-label="Seções">
      {(Object.keys(TABS) as Tab[]).map((t) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>
        {TABS[t]}{t === "funil" && pendingClient ? <span>{pendingClient}</span> : null}{t === "pedidos" ? <span>{requests.filter((r) => r.status === "aberto").length}</span> : null}</button>)}
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {result ? <p className="studioOk">{result.status === "aguardando" ? "Registrada: sai sozinha quando o WhatsApp da Mugô for ligado." : result.status === "enviado" ? (result.already_sent ? "Essa mensagem já tinha sido enviada." : "✓ Mensagem enviada pelo WhatsApp da Mugô.") : "Mensagem aberta no WhatsApp para envio."}</p> : null}
    {loading && !items.length ? <p>Carregando…</p> : null}

    {tab === "funil" ? <>
      <div className="calNav">
        <button type="button" className="ds-button" aria-label="Mês anterior" onClick={() => setMonth(shiftMonth(month, -1))}>‹</button>
        <h2 className="calRange">{MONTH_NAMES[Number(month.slice(5)) - 1]} {month.slice(0, 4)}</h2>
        <button type="button" className="ds-button" aria-label="Próximo mês" onClick={() => setMonth(shiftMonth(month, 1))}>›</button>
      </div>
      <div className="kanban">{(Object.keys(STAGES) as Stage[]).map((stage) => <section key={stage} className={`kanbanCol is-${stage} ${over === stage ? "is-over" : ""}`}
        onDragOver={canManage ? (e) => { e.preventDefault(); setOver(stage); } : undefined} onDragLeave={() => setOver((o) => (o === stage ? null : o))}
        onDrop={canManage ? (e) => onDrop(e, stage) : undefined}>
        <header><strong>{STAGES[stage]}</strong><span>{byStage(stage).length}</span></header>
        {byStage(stage).map((item) => {
          const when = localParts(item.scheduled_at);
          return <article key={item.id} className="kanbanCard" draggable={canManage}
            onDragStart={(e) => { e.dataTransfer.setData("text/plain", item.id); e.dataTransfer.effectAllowed = "move"; }}>
            <small>{when.label} · {when.time} · {STUDIO_FORMATS[item.format]}</small>
            <b>{item.title}</b>
            {item.client_feedback?.comment ? <p className="kanbanNote">“{item.client_feedback.comment}” — {item.client_feedback.reviewer_name || "cliente"}</p> : null}
            {item.stage === "ajuste" && !item.client_feedback?.comment && item.review_note ? <p className="kanbanNote">{item.review_note}</p> : null}
            {item.request ? <small>Enviado {dateTime(item.request.sent_at)}{item.request.contact_name ? ` para ${item.request.contact_name}` : ""}</small> : null}
            {canManage ? <select aria-label="Mover para" value={item.stage} onChange={(e) => void moveTo(item, e.target.value as Stage)}>
              {(Object.keys(STAGES) as Stage[]).map((s) => <option key={s} value={s} disabled={s === "com_cliente" && item.stage !== "com_cliente"}>{STAGES[s]}</option>)}</select> : null}
          </article>;
        })}
      </section>)}</div>
    </> : null}

    {tab === "pedidos" ? <ul className="approvalRequests">
      {!requests.length ? <li className="studioEmpty">Nenhum link enviado ainda. Use “Enviar ao cliente” no Calendário.</li> : null}
      {requests.map((r) => <li key={r.id} className={`is-${r.status}`}>
        <div><b>{MONTH_NAMES[Number(r.month.slice(5, 7)) - 1]}</b> · {r.items} pauta(s){r.contact_name ? ` · ${r.contact_name}` : ""}
          <small>Criado {dateTime(r.created_at)} · vale até {new Date(r.expires_at).toLocaleDateString("pt-BR")}{r.last_reminded_at ? ` · lembrete ${dateTime(r.last_reminded_at)}` : ""}</small></div>
        <span className={`studioStatus is-${r.status === "aberto" ? "em_revisao" : r.status === "concluido" ? "aprovado" : "rejeitado"}`}>{REQUEST_STATUS[r.status]}</span>
        {canManage && r.status === "aberto" ? <div className="studioActions">
          <button type="button" className="ds-button" disabled={Boolean(busy) || !contacts.length} onClick={() => { setTab("mensagens"); void openCompose("lembrete", r.id); }}>Lembrar no WhatsApp</button>
          <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => { if (window.confirm("Cancelar este link? O cliente não conseguirá mais abrir.")) void run("cancel", () => cancelApproval(r.id), "Não foi possível cancelar.").then((ok) => ok && load()); }}>Cancelar link</button>
        </div> : null}
      </li>)}
    </ul> : null}

    {tab === "contatos" ? <div className="contactList">
      <p className="libHint">Quem aprova e quem recebe relatórios. Para o envio pelo WhatsApp da Mugô, o telefone também precisa estar cadastrado no CRM.</p>
      {canManage ? <button type="button" className="ds-button is-primary" onClick={() => setEditing({ id: null, data: { ...emptyContact, is_primary: !contacts.length } })}>+ Contato</button> : null}
      <ul>{contacts.map((c) => <li key={c.id}>
        <div><b>{c.name}</b>{c.is_primary ? <span className="studioChip">principal</span> : null}<small>{c.role || "—"} · +{c.phone} · recebe {c.receives.map((r) => RECEIVES[r]).join(", ")}</small></div>
        {canManage ? <div className="studioActions">
          <button type="button" className="ds-button" onClick={() => setEditing({ id: c.id, data: { name: c.name, phone: c.phone, role: c.role || "", receives: c.receives, is_primary: c.is_primary } })}>Editar</button>
          <button type="button" className="studioLink" onClick={() => { if (window.confirm(`Remover ${c.name}?`)) void run("del", () => deleteContact(c.id), "Não foi possível remover.").then((ok) => ok && load()); }}>Remover</button>
        </div> : null}
      </li>)}</ul>
      {!contacts.length ? <p className="studioEmpty">Nenhum contato. Cadastre quem aprova o conteúdo deste cliente.</p> : null}
    </div> : null}

    {tab === "mensagens" ? <div className="messagePanel">
      {canManage ? <div className="studioActions">{(["semanal", "agenda", "trafego", "resultados"] as MessageKind[]).map((k) => <button key={k} type="button" className="ds-button" disabled={Boolean(busy) || !contacts.length} onClick={() => void openCompose(k)}>{MESSAGE_KINDS[k]}</button>)}</div> : null}
      {!contacts.length ? <p className="studioEmpty">Cadastre um contato na aba Contatos para enviar mensagens.</p> : null}
      <h3>Histórico</h3>
      <ul className="messageLog">{messages.map((m) => <li key={m.id} className={`is-${m.status}`}>
        <small>{dateTime(m.created_at)} · {MESSAGE_KINDS[m.kind]} · {m.contact_name || "—"} ({m.phone_masked}) · {m.channel === "mugozap" ? "MugôZap" : "link wa.me"}</small>
        <p>{m.preview?.text}</p>
        {m.status === "falhou" ? <small className="studioError">Falhou: {m.error_code}</small> : null}
      </li>)}</ul>
      {!messages.length ? <p className="studioEmpty">Nenhuma mensagem enviada ainda.</p> : null}
    </div> : null}

    <Drawer open={Boolean(editing)} title={editing?.id ? "Editar contato" : "Novo contato"} onClose={() => { if (!busy) setEditing(null); }}>
      {editing ? <form className="studioForm" onSubmit={saveContact}>
        <label>Nome<input required maxLength={120} value={editing.data.name} onChange={(e) => setEditing({ ...editing, data: { ...editing.data, name: e.target.value } })} /></label>
        <label>WhatsApp (com DDD)<input required inputMode="tel" maxLength={30} value={editing.data.phone} onChange={(e) => setEditing({ ...editing, data: { ...editing.data, phone: e.target.value } })} placeholder="(11) 98888-7777" /></label>
        <label>Função<input maxLength={80} value={editing.data.role || ""} onChange={(e) => setEditing({ ...editing, data: { ...editing.data, role: e.target.value } })} placeholder="Marketing, sócio…" /></label>
        <fieldset><legend>Recebe</legend>{(Object.keys(RECEIVES) as Receives[]).map((r) => <label key={r} className="studioCheck">
          <input type="checkbox" checked={editing.data.receives.includes(r)} onChange={(e) => setEditing({ ...editing, data: { ...editing.data, receives: e.target.checked ? [...editing.data.receives, r] : editing.data.receives.filter((x) => x !== r) } })} />{RECEIVES[r]}</label>)}</fieldset>
        <label className="studioCheck"><input type="checkbox" checked={editing.data.is_primary} onChange={(e) => setEditing({ ...editing, data: { ...editing.data, is_primary: e.target.checked } })} />Contato principal</label>
        <div className="studioActions"><button type="button" className="ds-button" onClick={() => setEditing(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy) || !editing.data.receives.length}>{busy === "contact" ? "Salvando…" : "Salvar"}</button></div>
      </form> : null}
    </Drawer>

    <Drawer open={Boolean(compose)} title={compose ? MESSAGE_KINDS[compose.kind] : "Mensagem"} description="Números vêm do painel; a frase de destaque é escrita pela IA a partir deles e pode ser editada." width="lg" onClose={() => { if (!busy) setCompose(null); }}>
      {compose ? <div className="studioForm">
        <label>Para<select value={compose.contact_id} onChange={(e) => void refreshPreview({ ...compose, contact_id: e.target.value, overrides: {} })}>
          <option value="">Escolha…</option>{contacts.map((c) => <option key={c.id} value={c.id}>{c.name} · recebe {c.receives.map((r) => RECEIVES[r]).join(", ")}</option>)}</select></label>
        {busy === "preview" ? <p>Montando a mensagem com os dados…</p> : null}
        {compose.preview ? <>
          {compose.preview.editable.map((k) => <label key={k}>{EDITABLE_LABEL[k] || k}<input maxLength={300} value={compose.overrides[k] || ""} onChange={(e) => setCompose({ ...compose, overrides: { ...compose.overrides, [k]: e.target.value } })} /></label>)}
          <div className="waPreview">
            {compose.preview.header_image ? <img src={compose.preview.header_image} alt="Arte enviada no cabeçalho" /> : null}
            <p>{compose.preview.editable.reduce((text, k) => text.replace(compose.preview!.params[k], compose.overrides[k] || compose.preview!.params[k]), compose.preview.text)}</p>
            <small>Template {compose.preview.template_name} · {compose.preview.phone_masked}</small>
          </div>
          {compose.preview.editable.length ? <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => void refreshPreview({ ...compose, overrides: {} })}>Gerar outra frase</button> : null}
        </> : null}
        <div className="studioActions"><button type="button" className="ds-button" onClick={() => setCompose(null)}>Cancelar</button>
          <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !compose.preview} onClick={() => void submitMessage()}>
            {busy === "send" ? "Enviando…" : channel === "mugozap" ? "Enviar pelo WhatsApp da Mugô" : "Abrir no WhatsApp"}</button></div>
      </div> : null}
    </Drawer>
  </div></Shell>;
}
