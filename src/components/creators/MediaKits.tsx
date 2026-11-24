import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  KIT_ACCEPT, KIT_STATUS, KIT_STATUS_COLOR, brl, kitStatus, kitDateBR as dateBR, saveMediaKit, uploadMediaKit, creatorCompact,
  type Creator, type KitDeal, type KitFile, type KitPrice, type KitStatus, type MediaKit,
} from "../../app/creators";

type Draft = { files: KitFile[]; prices: (Omit<KitPrice, "amount"> & { amount: string })[]; email: string; phone: string; contact: string; notes: string; deals: KitDeal[];
  status: KitStatus; status_note: string };
const EMPTY: Draft = { files: [], prices: [], email: "", phone: "", contact: "", notes: "", deals: [], status: "novo", status_note: "" };
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const toDraft = (kit?: MediaKit): Draft => kit ? {
  files: kit.files || [], email: kit.email || "", phone: kit.phone || "", contact: kit.contact || "", notes: kit.notes || "", deals: kit.deals || [],
  status: kitStatus(kit), status_note: kit.status_note || "",
  prices: (kit.prices || []).map((p) => ({ deliverable: p.deliverable, amount: p.amount == null ? "" : String(p.amount).replace(".", ","), notes: p.notes || "" })),
} : EMPTY;
const amountOf = (text: string) => { const n = Number(text.replace(/\./g, "").replace(",", ".")); return text.trim() && Number.isFinite(n) ? n : null; };
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

// Layout próprio da gaveta (seções empilhadas, campos ocupando a largura): não depende do CSS da página.
const STACK: CSSProperties = { display: "grid", gap: 20 };
const SECTION: CSSProperties = { display: "grid", gap: 10, paddingBottom: 18, borderBottom: "1px solid var(--ds-border, #e5e7eb)" };
const TWO: CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 };
const ROW: CSSProperties = { display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" };
const FULL: CSSProperties = { width: "100%", boxSizing: "border-box" };
const PRICE_ROW: CSSProperties = { display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(90px, 1fr) minmax(0, 2fr) auto", gap: 8, alignItems: "center" };
const DROP: CSSProperties = { display: "grid", gap: 4, justifyItems: "center", textAlign: "center", padding: "22px 16px", border: "2px dashed #cfd4dc",
  borderRadius: 14, background: "#fafafa", cursor: "pointer" };
const DROP_ON: CSSProperties = { borderColor: "#1f3b57", background: "#eef3f8" };
const LINK: CSSProperties = { background: "none", border: 0, padding: 0, color: "var(--ds-text-muted, #6b7280)", textDecoration: "underline", cursor: "pointer", font: "inherit", fontSize: 13 };
const LIST: CSSProperties = { display: "grid", gap: 6, margin: 0, paddingLeft: 18 };

// Modal centralizado do mídia kit (estilo próprio: não depende do CSS de outras telas).
const BACKDROP: CSSProperties = { position: "fixed", inset: 0, background: "rgba(20,22,18,.45)", display: "flex", alignItems: "center",
  justifyContent: "center", padding: 20, zIndex: 100 };
const PANEL: CSSProperties = { background: "#fff", borderRadius: 18, width: "100%", maxWidth: 760, maxHeight: "90vh", display: "flex",
  flexDirection: "column", boxShadow: "0 24px 60px rgba(0,0,0,.25)", outline: "none" };
const HEAD: CSSProperties = { display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, padding: "20px 24px", borderBottom: "1px solid #e8e5de" };
const BODY: CSSProperties = { padding: "20px 24px", overflowY: "auto" };
const FOOT: CSSProperties = { padding: "14px 24px", borderTop: "1px solid #e8e5de", display: "flex", justifyContent: "flex-end" };

function CenterModal({ title, subtitle, onClose, footer, children }: { title: string; subtitle?: string; onClose: () => void; footer: ReactNode; children: ReactNode }) {
  const panel = useRef<HTMLDivElement | null>(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; }, [onClose]);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close.current(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = overflow; if (previous?.isConnected) previous.focus(); };
  }, []);
  return <div style={BACKDROP} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={panel} tabIndex={-1} style={PANEL} role="dialog" aria-modal="true" aria-label={title}>
      <div style={HEAD}>
        <div><h2 style={{ margin: 0, fontSize: 20 }}>{title}</h2>{subtitle ? <small className="creatorMuted">{subtitle}</small> : null}</div>
        <button type="button" aria-label="Fechar" onClick={onClose} style={{ background: "none", border: 0, fontSize: 24, lineHeight: 1, cursor: "pointer", padding: "2px 6px", color: "#5f665f" }}>×</button>
      </div>
      <div style={BODY}>{children}</div>
      <div style={FOOT}>{footer}</div>
    </div>
  </div>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section style={SECTION}><h3 style={{ margin: 0, fontSize: 16 }}>{title}</h3>{children}</section>;
}

/**
 * Modal "Mídia kit" de um criador: arquivos (PDF/imagem ou link), valores por entregável, e-mail, telefone,
 * outro contato, fechamentos (histórico) e observações. Salva no banco por empresa.
 */
export function MediaKitModal({ creator, kit, canAct, onSaved, onClose }: {
  creator: Creator; kit?: MediaKit; canAct: boolean; onSaved: (kit: MediaKit) => void; onClose: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(kit));
  const [busy, setBusy] = useState<"save" | "upload" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [link, setLink] = useState("");
  const [dragging, setDragging] = useState(false);
  const [closing, setClosing] = useState<{ what: string; amount: string; closed_at: string; notes: string } | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(kit));
  const set = (patch: Partial<Draft>) => { setDraft((d) => ({ ...d, ...patch })); setSaved(null); };
  const setPrice = (i: number, patch: Partial<Draft["prices"][number]>) =>
    setDraft((d) => ({ ...d, prices: d.prices.map((p, j) => (j === i ? { ...p, ...patch } : p)) }));
  const close = () => { if (!busy && (!dirty || window.confirm("Há alterações não salvas. Fechar mesmo assim?"))) onClose(); };

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy("upload"); setError(null);
    try {
      const sent: KitFile[] = [];
      const accepted = [...files].filter((f) => KIT_ACCEPT.split(",").includes(f.type));
      if (!accepted.length) { setError("Envie PDF, PNG, JPG ou WEBP."); return; }
      for (const file of accepted) sent.push(await uploadMediaKit(file));
      setDraft((d) => ({ ...d, files: [...d.files, ...sent].slice(0, 10) }));
    } catch (cause) { setError(message(cause, "Não foi possível enviar o arquivo.")); }
    finally { setBusy(null); }
  }
  function addLink() {
    const url = link.trim();
    if (!/^https:\/\//.test(url)) { setError("Cole um link que comece com https:// (Drive, Canva, site do criador…)."); return; }
    setDraft((d) => ({ ...d, files: [...d.files, { url, name: "Link do mídia kit", kind: "link", uploaded_at: new Date().toISOString() }].slice(0, 10) }));
    setLink(""); setError(null);
  }
  async function save(next: Draft = draft, done = "✓ Mídia kit salvo.") {
    setBusy("save"); setError(null); setSaved(null);
    try {
      const result = await saveMediaKit(creator.id, {
        files: next.files, email: next.email.trim() || null, phone: next.phone.trim() || null, contact: next.contact.trim() || null,
        notes: next.notes.trim() || null, deals: next.deals, status: next.status, status_note: next.status_note.trim() || null,
        prices: next.prices.filter((p) => p.deliverable.trim()).map((p) => ({ deliverable: p.deliverable.trim(), amount: amountOf(p.amount), notes: p.notes?.trim() || null })),
      });
      const full = { ...result, creator_id: creator.id };
      onSaved(full); setDraft(toDraft(full)); setSaved(done);
      return true;
    } catch (cause) { setError(message(cause, "Não foi possível salvar.")); return false; }
    finally { setBusy(null); }
  }
  /** "Fechado": registra o fechamento e já salva (com o que mais estiver na tela), para a informação nunca se perder. */
  async function closeDeal() {
    if (!closing?.what.trim()) { setError("Diga o que foi fechado (ex.: 1 Reels + 3 Stories Black Friday)."); return; }
    const deal: KitDeal = { closed_at: closing.closed_at || today(), what: closing.what.trim(), amount: amountOf(closing.amount), notes: closing.notes.trim() || null };
    if (await save({ ...draft, status: "fechado", deals: [deal, ...draft.deals] }, `✓ Fechamento com @${creator.handle} registrado.`)) setClosing(null);
  }

  const footer = canAct ? <div style={ROW}>
    <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !dirty} onClick={() => void save()}>{busy === "save" ? "Salvando…" : "Salvar"}</button>
    {dirty ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => setDraft(toDraft(kit))}>Descartar</button> : null}
    <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={close}>Fechar</button>
  </div> : <button type="button" className="ds-button" onClick={close}>Fechar</button>;

  return <CenterModal title={`Mídia kit · @${creator.handle}`} subtitle={`${creatorCompact(creator.followers)} seguidores`} onClose={close} footer={footer}>
    <div style={STACK} aria-label={`Mídia kit de @${creator.handle}`}>
      {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
      {saved ? <p className="studioOk" role="status">{saved}</p> : null}

      <Section title="Status no CRM">
        <div style={TWO}>
          <label className="ds-field">Status
            <select style={FULL} value={draft.status} disabled={!canAct} onChange={(e) => set({ status: e.target.value as KitStatus })}>
              {Object.entries(KIT_STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select></label>
          <label className="ds-field">{draft.status === "nao_fechou" ? "Motivo de não ter fechado" : "Observação do status"}
            <input style={FULL} value={draft.status_note} maxLength={500} disabled={!canAct}
              placeholder={draft.status === "nao_fechou" ? "ex.: fora do orçamento, sem agenda" : "opcional"} onChange={(e) => set({ status_note: e.target.value })} /></label>
        </div>
        {kit?.status_at ? <small className="creatorMuted">{KIT_STATUS[kitStatus(kit)]} desde {new Date(kit.status_at).toLocaleDateString("pt-BR")}</small> : null}
      </Section>

      <Section title="Mídia kit">
        {draft.files.length ? <ul style={LIST}>{draft.files.map((f, i) => <li key={`${f.url}-${i}`}>
          <a href={f.url} target="_blank" rel="noreferrer">{f.name}</a> <small className="creatorMuted">{f.kind === "link" ? "link" : f.kind}</small>
          {canAct ? <> · <button type="button" style={LINK} onClick={() => set({ files: draft.files.filter((_, j) => j !== i) })}>Remover</button></> : null}
        </li>)}</ul> : <p className="creatorMuted" style={{ margin: 0 }}>Nenhum arquivo ainda.</p>}
        {canAct ? <>
          <label aria-label="Arraste o mídia kit aqui ou clique para escolher" style={{ ...DROP, ...(dragging ? DROP_ON : {}) }}
            onDragOver={(e) => { e.preventDefault(); if (!dragging) setDragging(true); }} onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); if (!busy) void upload(e.dataTransfer.files); }}>
            <b>{busy === "upload" ? "Enviando…" : dragging ? "Solte para enviar" : "Arraste o mídia kit aqui"}</b>
            <small className="creatorMuted">ou clique para escolher · PDF, PNG, JPG ou WEBP · até 10 arquivos</small>
            <input type="file" accept={KIT_ACCEPT} multiple hidden disabled={Boolean(busy)} onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} />
          </label>
          <div style={{ ...ROW, flexWrap: "nowrap" }}>
            <input style={{ ...FULL, flex: 1 }} value={link} onChange={(e) => setLink(e.target.value)} placeholder="ou cole um link (Drive, Canva…)" aria-label="Link do mídia kit" />
            <button type="button" className="ds-button" disabled={!link.trim()} onClick={addLink}>Adicionar link</button>
          </div>
        </> : null}
      </Section>

      <Section title="Valores">
        {draft.prices.length ? <div style={{ display: "grid", gap: 8 }}>
          <div style={{ ...PRICE_ROW, fontSize: 13 }} className="creatorMuted"><span>Entregável</span><span>Valor (R$)</span><span>Observação</span><span /></div>
          {draft.prices.map((p, i) => canAct ? <div key={i} style={PRICE_ROW}>
            <input style={FULL} value={p.deliverable} maxLength={120} placeholder="ex.: 1 Reels + 3 Stories" aria-label="Entregável" onChange={(e) => setPrice(i, { deliverable: e.target.value })} />
            <input style={FULL} value={p.amount} inputMode="decimal" placeholder="0,00" aria-label="Valor" onChange={(e) => setPrice(i, { amount: e.target.value })} />
            <input style={FULL} value={p.notes || ""} maxLength={300} placeholder="opcional" aria-label="Observação do valor" onChange={(e) => setPrice(i, { notes: e.target.value })} />
            <button type="button" style={LINK} onClick={() => set({ prices: draft.prices.filter((_, j) => j !== i) })}>Remover</button>
          </div> : <div key={i} style={PRICE_ROW}><span>{p.deliverable}</span><span>{brl(amountOf(p.amount))}</span><span>{p.notes}</span><span /></div>)}
        </div> : <p className="creatorMuted" style={{ margin: 0 }}>Nenhum valor cadastrado.</p>}
        {canAct && draft.prices.length < 30 ? <button type="button" className="ds-button" style={{ justifySelf: "start" }}
          onClick={() => set({ prices: [...draft.prices, { deliverable: "", amount: "", notes: "" }] })}>+ Valor</button> : null}
      </Section>

      <Section title="Contato">
        <div style={TWO}>
          <label className="ds-field">E-mail
            <input style={FULL} type="email" value={draft.email} maxLength={200} disabled={!canAct} placeholder="contato@criador.com" onChange={(e) => set({ email: e.target.value })} /></label>
          <label className="ds-field">Telefone / WhatsApp
            <input style={FULL} type="tel" value={draft.phone} maxLength={40} disabled={!canAct} placeholder="+55 11 99999-0000" onChange={(e) => set({ phone: e.target.value })} /></label>
        </div>
        <label className="ds-field">Outro contato (agência, empresário)
          <input style={FULL} value={draft.contact} maxLength={300} disabled={!canAct} onChange={(e) => set({ contact: e.target.value })} /></label>
      </Section>

      <Section title="Fechamentos">
        {draft.deals.length ? <ul style={LIST}>{draft.deals.map((deal, i) => <li key={deal.id || i}>
          <b>{dateBR(deal.closed_at)}</b> · {deal.what}{deal.amount != null ? ` · ${brl(deal.amount)}` : ""}{deal.notes ? <small className="creatorMuted"> · {deal.notes}</small> : null}
          {canAct ? <> · <button type="button" style={LINK} disabled={Boolean(busy)}
            onClick={() => { if (window.confirm("Apagar este fechamento do histórico?")) void save({ ...draft, deals: draft.deals.filter((_, j) => j !== i) }, "✓ Fechamento apagado."); }}>Apagar</button></> : null}
        </li>)}</ul> : <p className="creatorMuted" style={{ margin: 0 }}>Nenhum fechamento ainda.</p>}
        {canAct && !closing ? <button type="button" className="ds-button is-primary" style={{ justifySelf: "start" }} disabled={Boolean(busy)}
          onClick={() => setClosing({ what: "", amount: "", closed_at: today(), notes: "" })}>Fechado ✓</button> : null}
        {canAct && closing ? <div style={{ display: "grid", gap: 10 }} aria-label="Registrar fechamento">
          <label className="ds-field">O que foi fechado<input style={FULL} value={closing.what} maxLength={300} placeholder="ex.: 1 Reels + 3 Stories Black Friday"
            onChange={(e) => setClosing({ ...closing, what: e.target.value })} /></label>
          <div style={TWO}>
            <label className="ds-field">Valor (R$)<input style={FULL} value={closing.amount} inputMode="decimal" placeholder="0,00" onChange={(e) => setClosing({ ...closing, amount: e.target.value })} /></label>
            <label className="ds-field">Data<input style={FULL} type="date" value={closing.closed_at} onChange={(e) => setClosing({ ...closing, closed_at: e.target.value })} /></label>
          </div>
          <label className="ds-field">Observação<input style={FULL} value={closing.notes} maxLength={500} placeholder="opcional" onChange={(e) => setClosing({ ...closing, notes: e.target.value })} /></label>
          <div style={ROW}>
            <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void closeDeal()}>{busy === "save" ? "Salvando…" : "Registrar fechamento"}</button>
            <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => setClosing(null)}>Cancelar</button>
          </div>
        </div> : null}
      </Section>

      <label className="ds-field">Observações
        <textarea style={FULL} rows={4} value={draft.notes} maxLength={4000} disabled={!canAct} onChange={(e) => set({ notes: e.target.value })}
          placeholder="ex.: prazo de entrega, uso de imagem, permuta, histórico de campanhas" /></label>
    </div>
  </CenterModal>;
}

export function StatusChip({ status }: { status: KitStatus }) {
  const c = KIT_STATUS_COLOR[status];
  return <span style={{ background: c.bg, color: c.fg, borderRadius: 999, padding: "3px 10px", fontSize: 13, fontWeight: 600, whiteSpace: "nowrap" }}>{KIT_STATUS[status]}</span>;
}

const FILTERS: (KitStatus | "todos")[] = ["todos", "novo", "contatado", "negociando", "fechado", "nao_fechou"];
const CELL: CSSProperties = { padding: "10px 8px", borderBottom: "1px solid #eee", verticalAlign: "middle", textAlign: "left" };

/**
 * Aba "CRM criadores": quem fechou ou não, valores e contatos. Contagem por status (clique filtra), troca rápida de status,
 * último fechamento, total fechado e contato; "Abrir mídia kit" abre o modal com tudo.
 */
export default function MediaKits({ creators, kits, loading, canAct, onOpen, onStatus }: {
  creators: Creator[]; kits: Record<string, MediaKit>; loading: boolean; canAct: boolean;
  onOpen: (creator: Creator) => void; onStatus: (creator: Creator, status: KitStatus) => Promise<void>;
}) {
  const [filter, setFilter] = useState<KitStatus | "todos">("todos");
  const [busy, setBusy] = useState<string | null>(null);
  if (!creators.length) return <section className="creatorCard"><p className="creatorMuted">Nenhum criador nesta marca ainda. Analise um @ na aba Criadores e volte aqui para acompanhar a negociação.</p></section>;
  const count = (f: KitStatus | "todos") => f === "todos" ? creators.length : creators.filter((c) => kitStatus(kits[c.id]) === f).length;
  const shown = creators.filter((c) => filter === "todos" || kitStatus(kits[c.id]) === filter);
  const total = creators.reduce((sum, c) => sum + (kits[c.id]?.deals || []).reduce((s2, d) => s2 + (d.amount || 0), 0), 0);
  return <section className="creatorCard" aria-labelledby="creator-crm">
    <header><h2 id="creator-crm">CRM criadores · {creators.length}</h2></header>
    <p className="creatorMuted">Quem fechou ou não, desde quando e por quanto. Tudo fica salvo; só esta marca vê os valores negociados com ela.{total ? ` Total fechado: ${brl(total)}.` : ""}</p>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "4px 0 12px" }} role="group" aria-label="Filtrar por status">
      {FILTERS.map((f) => <button key={f} type="button" className={`ds-button${filter === f ? " is-primary" : ""}`} aria-pressed={filter === f} onClick={() => setFilter(f)}>
        {f === "todos" ? "Todos" : KIT_STATUS[f]} · {count(f)}</button>)}
    </div>
    {loading ? <p className="creatorMuted" role="status">Carregando…</p> : null}
    <div className="creatorScroll"><table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
      <thead><tr className="creatorMuted">
        <th style={CELL}>Criador</th><th style={CELL}>Status</th><th style={CELL}>Valores</th><th style={CELL}>Último fechamento</th><th style={CELL}>Total fechado</th><th style={CELL}>Contatos</th><th style={CELL} aria-label="Ações" />
      </tr></thead>
      <tbody>{shown.map((creator) => {
        const kit = kits[creator.id];
        const status = kitStatus(kit);
        const last = kit?.deals?.[0];
        const closed = (kit?.deals || []).reduce((sum, d) => sum + (d.amount || 0), 0);
        return <tr key={creator.id}>
          <td style={CELL}><a href={creator.profile_url || undefined} target="_blank" rel="noreferrer"><b>@{creator.handle}</b></a><br /><small className="creatorMuted">{creatorCompact(creator.followers)} seguidores</small></td>
          <td style={CELL}>{canAct ? <select aria-label={`Status de @${creator.handle}`} value={status} disabled={busy === creator.id}
              style={{ border: 0, borderRadius: 999, padding: "4px 10px", fontWeight: 600, background: KIT_STATUS_COLOR[status].bg, color: KIT_STATUS_COLOR[status].fg }}
              onChange={async (e) => { setBusy(creator.id); try { await onStatus(creator, e.target.value as KitStatus); } finally { setBusy(null); } }}>
              {Object.entries(KIT_STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select> : <StatusChip status={status} />}
            {kit?.status_note ? <><br /><small className="creatorMuted">{kit.status_note}</small></> : null}</td>
          <td style={CELL}>{kit?.prices?.length ? <>{kit.prices.slice(0, 3).map((p, i) => <div key={i}><small>{p.deliverable}: <b>{brl(p.amount)}</b></small></div>)}
            {kit.prices.length > 3 ? <small className="creatorMuted">+{kit.prices.length - 3} valor(es)</small> : null}</> : <span className="creatorMuted">—</span>}</td>
          <td style={CELL}>{last ? <>{dateBR(last.closed_at)}<br /><small className="creatorMuted">{last.what}</small></> : <span className="creatorMuted">—</span>}</td>
          <td style={CELL}>{closed ? brl(closed) : <span className="creatorMuted">—</span>}</td>
          <td style={CELL}>{kit?.email || kit?.phone || kit?.contact ? <>{kit?.email ? <a href={`mailto:${kit.email}`}>{kit.email}</a> : null}{kit?.email && kit?.phone ? <br /> : null}{kit?.phone ? <a href={`https://wa.me/${kit.phone.replace(/\D/g, "")}`} target="_blank" rel="noreferrer">{kit.phone}</a> : null}
            {kit?.contact ? <><br /><small className="creatorMuted">{kit.contact}</small></> : null}</>
            : <span className="creatorMuted">—</span>}</td>
          <td style={CELL}><button type="button" className="ds-button" onClick={() => onOpen(creator)}>Abrir mídia kit</button></td>
        </tr>;
      })}</tbody>
    </table></div>
    {!shown.length ? <p className="creatorMuted">Nenhum criador com esse status.</p> : null}
  </section>;
}
