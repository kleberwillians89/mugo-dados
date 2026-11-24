import { useEffect, useState } from "react";
import {
  KIT_ACCEPT, brl, listMediaKits, saveMediaKit, uploadMediaKit, creatorCompact,
  type Creator, type KitDeal, type KitFile, type KitPrice, type MediaKit,
} from "../../app/creators";

type Draft = { files: KitFile[]; prices: (Omit<KitPrice, "amount"> & { amount: string })[]; email: string; phone: string; contact: string; notes: string; deals: KitDeal[] };
const EMPTY: Draft = { files: [], prices: [], email: "", phone: "", contact: "", notes: "", deals: [] };
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const dateBR = (iso: string) => iso.split("-").reverse().join("/");
const toDraft = (kit?: MediaKit): Draft => kit ? {
  files: kit.files || [], email: kit.email || "", phone: kit.phone || "", contact: kit.contact || "", notes: kit.notes || "", deals: kit.deals || [],
  prices: (kit.prices || []).map((p) => ({ deliverable: p.deliverable, amount: p.amount == null ? "" : String(p.amount).replace(".", ","), notes: p.notes || "" })),
} : EMPTY;
const amountOf = (text: string) => { const n = Number(text.replace(/\./g, "").replace(",", ".")); return text.trim() && Number.isFinite(n) ? n : null; };
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

/**
 * Aba "Mídia kit e valores": para cada criador da marca, o mídia kit (PDF/imagem ou link), os valores por entregável,
 * o contato e observações. Fica salvo no banco por empresa; quem só lê vê, agência e client_admin editam.
 */
export default function MediaKits({ creators, canAct }: { creators: Creator[]; canAct: boolean }) {
  const [kits, setKits] = useState<Record<string, MediaKit>>({});
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState<"save" | "upload" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [link, setLink] = useState("");
  const [closing, setClosing] = useState<{ what: string; amount: string; closed_at: string; notes: string } | null>(null);

  useEffect(() => {
    let alive = true;
    listMediaKits().then((r) => { if (alive) setKits(Object.fromEntries(r.kits.map((k) => [k.creator_id, k]))); })
      .catch((cause) => { if (alive) setError(message(cause, "Não foi possível carregar os mídia kits.")); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const dirty = open ? JSON.stringify(draft) !== JSON.stringify(toDraft(kits[open])) : false;
  const start = (id: string) => {
    if (open === id) { if (!dirty || window.confirm("Há alterações não salvas. Fechar mesmo assim?")) setOpen(null); return; }
    if (dirty && !window.confirm("Há alterações não salvas no criador aberto. Trocar mesmo assim?")) return;
    setOpen(id); setDraft(toDraft(kits[id])); setError(null); setSaved(null); setLink(""); setClosing(null);
  };
  const setPrice = (i: number, patch: Partial<Draft["prices"][number]>) =>
    setDraft((d) => ({ ...d, prices: d.prices.map((p, j) => (j === i ? { ...p, ...patch } : p)) }));

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
  async function save(creator: Creator, next: Draft = draft, done = `✓ Mídia kit de @${creator.handle} salvo.`) {
    setBusy("save"); setError(null); setSaved(null);
    try {
      const kit = await saveMediaKit(creator.id, {
        files: next.files, email: next.email.trim() || null, phone: next.phone.trim() || null, contact: next.contact.trim() || null,
        notes: next.notes.trim() || null, deals: next.deals,
        prices: next.prices.filter((p) => p.deliverable.trim()).map((p) => ({ deliverable: p.deliverable.trim(), amount: amountOf(p.amount), notes: p.notes?.trim() || null })),
      });
      setKits((k) => ({ ...k, [creator.id]: { ...kit, creator_id: creator.id } }));
      setDraft(toDraft({ ...kit, creator_id: creator.id }));
      setSaved(done);
      return true;
    } catch (cause) { setError(message(cause, "Não foi possível salvar.")); return false; }
    finally { setBusy(null); }
  }
  /** "Fechado": registra o fechamento e já salva (com o que mais estiver na tela), para a informação nunca se perder. */
  async function closeDeal(creator: Creator) {
    if (!closing?.what.trim()) { setError("Diga o que foi fechado (ex.: 1 Reels + 3 Stories Black Friday)."); return; }
    const deal: KitDeal = { closed_at: closing.closed_at || today(), what: closing.what.trim(), amount: amountOf(closing.amount), notes: closing.notes.trim() || null };
    if (await save(creator, { ...draft, deals: [deal, ...draft.deals] }, `✓ Fechamento com @${creator.handle} registrado.`)) setClosing(null);
  }

  if (!creators.length) return <section className="creatorCard"><p className="creatorMuted">Nenhum criador nesta marca ainda. Analise um @ na aba Criadores e volte aqui para guardar o mídia kit e os valores.</p></section>;

  return <section className="creatorCard" aria-labelledby="creator-kits">
    <header><h2 id="creator-kits">Mídia kit e valores · {creators.length}</h2></header>
    <p className="creatorMuted">Guarde o mídia kit e os valores de cada criador. Fica salvo na plataforma e só esta marca vê os valores negociados com ela.</p>
    {loading ? <p className="creatorMuted" role="status">Carregando…</p> : null}
    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
    <ul className="creatorListItems">{creators.map((creator) => {
      const kit = kits[creator.id];
      const amounts = (kit?.prices || []).map((p) => p.amount).filter((a): a is number => a != null);
      const isOpen = open === creator.id;
      return <li key={creator.id} style={{ flexWrap: "wrap" }}>
        <div className="creatorIdentity"><div>
          <a href={creator.profile_url || undefined} target="_blank" rel="noreferrer">@{creator.handle}</a>
          <small>{creatorCompact(creator.followers)} seguidores</small>
        </div></div>
        <span className="creatorMuted">{kit?.files?.length ? `Kit ✓ (${kit.files.length})` : "Sem mídia kit"}
          {amounts.length ? ` · ${kit!.prices.length} valor(es) · a partir de ${brl(Math.min(...amounts))}` : ""}
          {kit?.deals?.length ? ` · Fechado ✓ ${dateBR(kit.deals[0].closed_at)}${kit.deals.length > 1 ? ` (${kit.deals.length}x)` : ""}` : ""}</span>
        <button type="button" className={`ds-button${isOpen ? " is-primary" : ""}`} aria-expanded={isOpen} onClick={() => start(creator.id)}>
          {isOpen ? "Fechar" : canAct ? (kit ? "Ver e editar" : "Adicionar mídia kit") : "Ver"}</button>
        {isOpen ? <div style={{ flexBasis: "100%", display: "grid", gap: 12, paddingTop: 8 }} aria-label={`Mídia kit de @${creator.handle}`}>
          <div>
            <b>Mídia kit</b>
            {draft.files.length ? <ul>{draft.files.map((f, i) => <li key={`${f.url}-${i}`}>
              <a href={f.url} target="_blank" rel="noreferrer">{f.name}</a> <small className="creatorMuted">{f.kind === "link" ? "link" : f.kind}</small>
              {canAct ? <> <button type="button" className="studioLink" onClick={() => setDraft((d) => ({ ...d, files: d.files.filter((_, j) => j !== i) }))}>Remover</button></> : null}
            </li>)}</ul> : <p className="creatorMuted">Nenhum arquivo ainda.</p>}
            {canAct ? <div className="creatorRow">
              <label className="ds-button">{busy === "upload" ? "Enviando…" : "Enviar PDF ou imagem"}
                <input type="file" accept={KIT_ACCEPT} multiple hidden disabled={Boolean(busy)} onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} /></label>
              <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="ou cole um link (Drive, Canva…)" aria-label="Link do mídia kit" />
              <button type="button" className="ds-button" disabled={!link.trim()} onClick={addLink}>Adicionar link</button>
            </div> : null}
          </div>
          <div>
            <b>Valores</b>
            <div className="creatorScroll"><table className="ds-table">
              <thead><tr><th>Entregável</th><th className="is-number">Valor (R$)</th><th>Observação</th>{canAct ? <th aria-label="Ações" /> : null}</tr></thead>
              <tbody>{draft.prices.length ? draft.prices.map((p, i) => <tr key={i}>
                <td>{canAct ? <input value={p.deliverable} maxLength={120} placeholder="ex.: 1 Reels + 3 Stories" aria-label="Entregável" onChange={(e) => setPrice(i, { deliverable: e.target.value })} /> : p.deliverable}</td>
                <td className="is-number">{canAct ? <input value={p.amount} inputMode="decimal" placeholder="0,00" aria-label="Valor" onChange={(e) => setPrice(i, { amount: e.target.value })} /> : brl(amountOf(p.amount))}</td>
                <td>{canAct ? <input value={p.notes || ""} maxLength={300} placeholder="opcional" aria-label="Observação do valor" onChange={(e) => setPrice(i, { notes: e.target.value })} /> : p.notes}</td>
                {canAct ? <td><button type="button" className="studioLink" onClick={() => setDraft((d) => ({ ...d, prices: d.prices.filter((_, j) => j !== i) }))}>Remover</button></td> : null}
              </tr>) : <tr><td colSpan={canAct ? 4 : 3} className="creatorMuted">Nenhum valor cadastrado.</td></tr>}</tbody>
            </table></div>
            {canAct && draft.prices.length < 30 ? <button type="button" className="ds-button" onClick={() => setDraft((d) => ({ ...d, prices: [...d.prices, { deliverable: "", amount: "", notes: "" }] }))}>+ Valor</button> : null}
          </div>
          <div className="creatorRow">
            <label className="ds-field">E-mail
              <input type="email" value={draft.email} maxLength={200} disabled={!canAct} placeholder="contato@criador.com" onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))} /></label>
            <label className="ds-field">Telefone / WhatsApp
              <input type="tel" value={draft.phone} maxLength={40} disabled={!canAct} placeholder="+55 11 99999-0000" onChange={(e) => setDraft((d) => ({ ...d, phone: e.target.value }))} /></label>
          </div>
          <label className="ds-field">Outro contato (agência, empresário)
            <input value={draft.contact} maxLength={300} disabled={!canAct} onChange={(e) => setDraft((d) => ({ ...d, contact: e.target.value }))} /></label>
          <div>
            <b>Fechamentos</b>
            {draft.deals.length ? <ul>{draft.deals.map((deal, i) => <li key={deal.id || i}>
              <b>{dateBR(deal.closed_at)}</b> · {deal.what}{deal.amount != null ? ` · ${brl(deal.amount)}` : ""}{deal.notes ? <small className="creatorMuted"> · {deal.notes}</small> : null}
              {canAct ? <> <button type="button" className="studioLink" disabled={Boolean(busy)}
                onClick={() => { if (window.confirm("Apagar este fechamento do histórico?")) void save(creator, { ...draft, deals: draft.deals.filter((_, j) => j !== i) }, "✓ Fechamento apagado."); }}>Apagar</button></> : null}
            </li>)}</ul> : <p className="creatorMuted">Nenhum fechamento ainda.</p>}
            {canAct && !closing ? <button type="button" className="ds-button is-primary" disabled={Boolean(busy)}
              onClick={() => setClosing({ what: "", amount: "", closed_at: today(), notes: "" })}>Fechado ✓</button> : null}
            {canAct && closing ? <div className="creatorRow" aria-label="Registrar fechamento">
              <label className="ds-field">O que foi fechado<input value={closing.what} maxLength={300} placeholder="ex.: 1 Reels + 3 Stories Black Friday"
                onChange={(e) => setClosing({ ...closing, what: e.target.value })} /></label>
              <label className="ds-field">Valor (R$)<input value={closing.amount} inputMode="decimal" placeholder="0,00" onChange={(e) => setClosing({ ...closing, amount: e.target.value })} /></label>
              <label className="ds-field">Data<input type="date" value={closing.closed_at} onChange={(e) => setClosing({ ...closing, closed_at: e.target.value })} /></label>
              <label className="ds-field">Observação<input value={closing.notes} maxLength={500} placeholder="opcional" onChange={(e) => setClosing({ ...closing, notes: e.target.value })} /></label>
              <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void closeDeal(creator)}>{busy === "save" ? "Salvando…" : "Registrar fechamento"}</button>
              <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => setClosing(null)}>Cancelar</button>
            </div> : null}
          </div>
          <label className="ds-field">Observações
            <textarea rows={3} value={draft.notes} maxLength={4000} disabled={!canAct} onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
              placeholder="ex.: prazo de entrega, uso de imagem, permuta, histórico de campanhas" /></label>
          {canAct ? <div className="creatorActions">
            <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !dirty} onClick={() => void save(creator)}>{busy === "save" ? "Salvando…" : "Salvar"}</button>
            {dirty ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => setDraft(toDraft(kits[creator.id]))}>Descartar</button> : null}
          </div> : null}
          {saved ? <p className="studioOk" role="status">{saved}</p> : null}
        </div> : null}
      </li>;
    })}</ul>
  </section>;
}
