import { useCallback, useEffect, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { addReference, deleteReference, listReferences, uploadReference, type BrandReference } from "../../app/studio";
import Linkified from "./Linkified";

const when = (iso: string) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
const isImage = (url: string) => /\.(jpe?g|png|webp)(\?|$)/i.test(url);

/** Links e artes que o cliente gosta: norte visual para a equipe e para a IA de conteúdo. */
export default function BrandReferences({ isAgency }: { isAgency: boolean }) {
  const clientId = getActiveClientId();
  const [refs, setRefs] = useState<BrandReference[] | null>(null);
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { const r = await listReferences(); if (getActiveClientId() === clientId) setRefs(r.references || []); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível carregar as referências."); setRefs([]); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  async function save(input: { url: string; kind: "link" | "arte" }) {
    setBusy(true); setError(null); setOk(null);
    try {
      await addReference({ ...input, note: note.trim() || null });
      setUrl(""); setNote("");
      setOk(isAgency ? "Referência salva." : "Referência enviada: a equipe Mugô foi avisada.");
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar."); }
    finally { setBusy(false); }
  }

  async function onUpload(file: File | undefined) {
    if (!file) return;
    setBusy(true); setError(null);
    try { await save({ url: await uploadReference(file), kind: "arte" }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível enviar a imagem."); setBusy(false); }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (url.trim()) void save({ url: url.trim(), kind: "link" });
  }

  return <section className="brandRefs" aria-label="Referências">
    <p className="libHint">Cole aqui posts, perfis e artes que vocês gostam (Instagram, Pinterest, Behance, Drive) ou envie uma imagem. A IA usa essas referências ao montar as próximas pautas do calendário (formato, estética e tom), e a equipe Mugô também vê tudo aqui.</p>
    <form className="studioForm" onSubmit={submit}>
      <label>Link da referência<input type="url" inputMode="url" placeholder="https://www.instagram.com/p/…" value={url} onChange={(e) => setUrl(e.target.value)} /></label>
      <label>O que você gostou (opcional)<textarea rows={2} maxLength={500} placeholder="Ex.: as cores, o jeito de mostrar o produto, a legenda curta" value={note} onChange={(e) => setNote(e.target.value)} /></label>
      <div className="studioActions">
        <button className="ds-button is-primary" disabled={busy || !url.trim()}>{busy ? "Enviando…" : "Adicionar link"}</button>
        <label className="ds-button" aria-disabled={busy}>Enviar imagem
          <input type="file" accept="image/jpeg,image/png,image/webp" hidden disabled={busy} onChange={(e) => { void onUpload(e.target.files?.[0]); e.target.value = ""; }} /></label>
      </div>
    </form>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {ok ? <p className="studioOk">{ok}</p> : null}
    {refs === null ? <p className="libHint">Carregando…</p> : null}
    {refs && !refs.length ? <p className="studioEmpty">Nenhuma referência ainda.</p> : null}
    <ul className="brandRefList">{(refs || []).map((r) => <li key={r.id}>
      {r.kind === "arte" || isImage(r.url) ? <a href={r.url} target="_blank" rel="noopener noreferrer"><img src={r.url} alt="Referência" loading="lazy" /></a> : null}
      <div>
        <small>{r.author_side === "mugo" ? "Equipe Mugô" : "Cliente"} · {when(r.created_at)}</small>
        {r.kind === "link" ? <p><Linkified text={r.url} /></p> : null}
        {r.note ? <p>{r.note}</p> : null}
      </div>
      {r.can_delete ? <button type="button" className="studioLink" disabled={busy} onClick={() => { if (window.confirm("Remover esta referência?")) void deleteReference(r.id).then(load).catch(() => setError("Não foi possível remover.")); }}>Remover</button> : null}
    </li>)}</ul>
  </section>;
}
