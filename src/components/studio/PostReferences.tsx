import { useCallback, useEffect, useState } from "react";
import { addItemReference, deleteReference, listItemReferences, type BrandReference } from "../../app/studio";
import Linkified from "./Linkified";

/** Referências de UM post (links de posts/artes no estilo desejado). A IA de conteúdo deste post usa. */
export default function PostReferences({ itemId, isAgency }: { itemId: string; isAgency: boolean }) {
  const [refs, setRefs] = useState<BrandReference[] | null>(null);
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setRefs((await listItemReferences(itemId)).references || []); } catch { setRefs([]); }
  }, [itemId]);
  useEffect(() => { void load(); }, [load]);

  async function add() {
    if (!url.trim()) return;
    setBusy(true); setError(null);
    try { await addItemReference(itemId, { url: url.trim(), note: note.trim() || null }); setUrl(""); setNote(""); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar a referência."); }
    finally { setBusy(false); }
  }

  return <section className="postRefs" aria-label="Referências deste post">
    <h4>Referências deste post{refs?.length ? ` (${refs.length})` : ""}</h4>
    <p className="libHint">{isAgency ? "Links de posts ou artes no estilo que queremos. A IA de conteúdo deste post usa." : "Gostou de algum post ou arte nesse estilo? Cole o link aqui: a equipe Mugô é avisada."}</p>
    <ul className="brandRefList">{(refs || []).map((r) => <li key={r.id}>
      <div><small>{r.author_side === "mugo" ? "Equipe Mugô" : "Cliente"}</small><p><Linkified text={r.url} /></p>{r.note ? <p>{r.note}</p> : null}</div>
      {r.can_delete ? <button type="button" className="studioLink" disabled={busy} onClick={() => void deleteReference(r.id).then(load).catch(() => setError("Não foi possível remover."))}>Remover</button> : null}
    </li>)}</ul>
    <div className="postRefForm" role="group" aria-label="Nova referência">
      <input type="url" inputMode="url" placeholder="https://www.instagram.com/p/… ou Pinterest, Drive" value={url} onChange={(e) => setUrl(e.target.value)} />
      <input placeholder="O que gostou (opcional)" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      <button type="button" className="ds-button" disabled={busy || !url.trim()} onClick={() => void add()}>{busy ? "Salvando…" : "Adicionar"}</button>
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
  </section>;
}
