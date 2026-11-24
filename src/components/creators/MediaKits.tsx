import { useState, type CSSProperties, type ReactNode } from "react";
import Drawer from "../Drawer";
import {
  KIT_ACCEPT, brl, kitDateBR as dateBR, saveMediaKit, uploadMediaKit, creatorCompact,
  kitSummary, type Creator, type KitDeal, type KitFile, type KitPrice, type MediaKit,
} from "../../app/creators";

type Draft = { files: KitFile[]; prices: (Omit<KitPrice, "amount"> & { amount: string })[]; email: string; phone: string; contact: string; notes: string; deals: KitDeal[] };
const EMPTY: Draft = { files: [], prices: [], email: "", phone: "", contact: "", notes: "", deals: [] };
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const toDraft = (kit?: MediaKit): Draft => kit ? {
  files: kit.files || [], email: kit.email || "", phone: kit.phone || "", contact: kit.contact || "", notes: kit.notes || "", deals: kit.deals || [],
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
const LINK: CSSProperties = { background: "none", border: 0, padding: 0, color: "var(--ds-text-muted, #6b7280)", textDecoration: "underline", cursor: "pointer", font: "inherit", fontSize: 13 };
const LIST: CSSProperties = { display: "grid", gap: 6, margin: 0, paddingLeft: 18 };

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section style={SECTION}><h3 style={{ margin: 0, fontSize: 16 }}>{title}</h3>{children}</section>;
}

/**
 * Gaveta "Mídia kit" de um criador: arquivos (PDF/imagem ou link), valores por entregável, e-mail, telefone,
 * outro contato, fechamentos (histórico) e observações. Salva no banco por empresa.
 */
export function MediaKitDrawer({ creator, kit, canAct, onSaved, onClose }: {
  creator: Creator; kit?: MediaKit; canAct: boolean; onSaved: (kit: MediaKit) => void; onClose: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(kit));
  const [busy, setBusy] = useState<"save" | "upload" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [link, setLink] = useState("");
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
      for (const file of [...files]) sent.push(await uploadMediaKit(file));
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
        notes: next.notes.trim() || null, deals: next.deals,
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
    if (await save({ ...draft, deals: [deal, ...draft.deals] }, `✓ Fechamento com @${creator.handle} registrado.`)) setClosing(null);
  }

  const footer = canAct ? <div style={ROW}>
    <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !dirty} onClick={() => void save()}>{busy === "save" ? "Salvando…" : "Salvar"}</button>
    {dirty ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => setDraft(toDraft(kit))}>Descartar</button> : null}
    <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={close}>Fechar</button>
  </div> : <button type="button" className="ds-button" onClick={close}>Fechar</button>;

  return <Drawer open width="lg" title={`Mídia kit · @${creator.handle}`} description={`${creatorCompact(creator.followers)} seguidores`} onClose={close} footer={footer}>
    <div style={STACK} aria-label={`Mídia kit de @${creator.handle}`}>
      {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
      {saved ? <p className="studioOk" role="status">{saved}</p> : null}

      <Section title="Mídia kit">
        {draft.files.length ? <ul style={LIST}>{draft.files.map((f, i) => <li key={`${f.url}-${i}`}>
          <a href={f.url} target="_blank" rel="noreferrer">{f.name}</a> <small className="creatorMuted">{f.kind === "link" ? "link" : f.kind}</small>
          {canAct ? <> · <button type="button" style={LINK} onClick={() => set({ files: draft.files.filter((_, j) => j !== i) })}>Remover</button></> : null}
        </li>)}</ul> : <p className="creatorMuted" style={{ margin: 0 }}>Nenhum arquivo ainda.</p>}
        {canAct ? <>
          <label className="ds-button" style={{ justifySelf: "start", cursor: "pointer" }}>{busy === "upload" ? "Enviando…" : "Enviar PDF ou imagem"}
            <input type="file" accept={KIT_ACCEPT} multiple hidden disabled={Boolean(busy)} onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} /></label>
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
  </Drawer>;
}

/** Aba "Mídia kit e valores": a lista dos criadores da marca com o resumo e o botão que abre a gaveta. */
export default function MediaKits({ creators, kits, loading, onOpen }: {
  creators: Creator[]; kits: Record<string, MediaKit>; loading: boolean; onOpen: (creator: Creator) => void;
}) {
  if (!creators.length) return <section className="creatorCard"><p className="creatorMuted">Nenhum criador nesta marca ainda. Analise um @ na aba Criadores e volte aqui para guardar o mídia kit e os valores.</p></section>;
  return <section className="creatorCard" aria-labelledby="creator-kits">
    <header><h2 id="creator-kits">Mídia kit e valores · {creators.length}</h2></header>
    <p className="creatorMuted">Guarde o mídia kit, os valores e os fechamentos de cada criador. Fica salvo na plataforma e só esta marca vê os valores negociados com ela.</p>
    {loading ? <p className="creatorMuted" role="status">Carregando…</p> : null}
    <ul className="creatorListItems">{creators.map((creator) => <li key={creator.id}>
      <div className="creatorIdentity"><div>
        <a href={creator.profile_url || undefined} target="_blank" rel="noreferrer">@{creator.handle}</a>
        <small>{creatorCompact(creator.followers)} seguidores</small>
      </div></div>
      <span className="creatorMuted">{kitSummary(kits[creator.id])}</span>
      <button type="button" className="ds-button" onClick={() => onOpen(creator)}>Abrir mídia kit</button>
    </li>)}</ul>
  </section>;
}
