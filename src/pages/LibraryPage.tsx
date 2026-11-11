import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { LIBRARY_ACCEPT, LIBRARY_CATEGORIES, addLibraryLink, deleteLibraryItem, formatBytes, listLibrary, previewKind, uploadLibraryFile,
  type LibraryCategory, type LibraryItem } from "../app/library";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/studio.css";

type Section = "todos" | "materiais" | "aprovados";
const SECTIONS: { key: Section; label: string }[] = [
  { key: "todos", label: "Todos" }, { key: "materiais", label: "Materiais da marca" }, { key: "aprovados", label: "Posts aprovados" },
];
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
type Upload = { name: string; pct: number; error?: string };

/**
 * Biblioteca da marca: tudo o que a equipe e o cliente usam para criar, num lugar só. Arquivos (enviados direto
 * para o armazenamento) e links (Drive, Canva, Figma), por categoria. A arte dos posts aprovados entra sozinha.
 */
export default function LibraryPage() {
  const clientId = getActiveClientId();
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [approved, setApproved] = useState<LibraryItem[]>([]);
  const [team, setTeam] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<Section>("todos");
  const [category, setCategory] = useState<LibraryCategory | "todas">("todas");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState<"link" | null>(null);
  const [uploadCategory, setUploadCategory] = useState<LibraryCategory>("produto");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [viewing, setViewing] = useState<LibraryItem | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await listLibrary();
      if (getActiveClientId() !== clientId) return;
      setItems(r.items); setApproved(r.approved); setTeam(r.team);
    } catch (cause) { setError(message(cause, "Não foi possível abrir a Biblioteca.")); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  const shown = useMemo(() => {
    const pool = section === "aprovados" ? approved : section === "materiais" ? items : [...items, ...approved];
    const q = query.trim().toLowerCase();
    return pool.filter((i) => (section === "aprovados" || category === "todas" || i.category === category)
      && (!q || `${i.title} ${i.note || ""}`.toLowerCase().includes(q)));
  }, [items, approved, section, category, query]);
  const counts = useMemo(() => {
    const c: Partial<Record<LibraryCategory, number>> = {};
    items.forEach((i) => { c[i.category as LibraryCategory] = (c[i.category as LibraryCategory] || 0) + 1; });
    return c;
  }, [items]);

  async function sendFiles(files: FileList | File[]) {
    setError(null);
    for (const file of Array.from(files)) {
      setUploads((u) => [...u, { name: file.name, pct: 0 }]);
      const set = (patch: Partial<Upload>) => setUploads((u) => u.map((x) => (x.name === file.name ? { ...x, ...patch } : x)));
      try {
        const r = await uploadLibraryFile(file, uploadCategory, (pct) => set({ pct }));
        setItems((list) => [r.item, ...list]);
        setUploads((u) => u.filter((x) => x.name !== file.name));
      } catch (cause) { set({ error: message(cause, "O envio falhou.") }); }
    }
  }

  async function remove(item: LibraryItem) {
    if (!window.confirm(`Apagar "${item.title}" da Biblioteca?`)) return;
    try { await deleteLibraryItem(item.id); setItems((list) => list.filter((i) => i.id !== item.id)); setViewing(null); }
    catch (cause) { setError(message(cause, "Não foi possível apagar.")); }
  }

  return <Shell title="Biblioteca" variant="editorial"><div className="ds-page studioPage libPage">
    <PageHeader company={getActiveClientName() || "empresa"} title="Biblioteca"
      controls={<div className="libActions">
        <button type="button" className="ds-button" onClick={() => setAdding(adding ? null : "link")}>Adicionar link</button>
        <button type="button" className="ds-button is-primary" onClick={() => fileInput.current?.click()}>Enviar arquivo</button>
      </div>} />
    <p className="libIntro">{team ? "Produto, logo, fotos, vídeos brutos e referências da marca. O cliente também envia daqui."
      : "Mande aqui fotos de produto, logo, vídeos e referências. A equipe Mugô usa tudo para criar."}</p>

    <input ref={fileInput} type="file" multiple hidden accept={LIBRARY_ACCEPT.join(",")}
      onChange={(e) => { if (e.target.files?.length) void sendFiles(e.target.files); e.target.value = ""; }} />
    <div className={`libDrop${dragOver ? " is-over" : ""}`} onDragOver={(e) => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files.length) void sendFiles(e.dataTransfer.files); }}>
      <span>Arraste arquivos aqui ou <button type="button" className="ds-link" onClick={() => fileInput.current?.click()}>escolha no computador</button></span>
      <label>Entra como<select value={uploadCategory} onChange={(e) => setUploadCategory(e.target.value as LibraryCategory)}>
        {(Object.keys(LIBRARY_CATEGORIES) as LibraryCategory[]).map((c) => <option key={c} value={c}>{LIBRARY_CATEGORIES[c]}</option>)}</select></label>
      <small>Imagem, vídeo, PDF, Office ou ZIP, até 500 MB</small>
    </div>
    {uploads.length ? <ul className="libUploads" aria-label="Envios">{uploads.map((u) => <li key={u.name}>
      <span>{u.name}</span>{u.error ? <b className="libErr">{u.error}</b> : <span className="briefBar"><i style={{ width: `${u.pct}%` }} /></span>}
      {u.error ? <button type="button" className="ds-link" onClick={() => setUploads((x) => x.filter((y) => y.name !== u.name))}>Fechar</button> : <small>{u.pct}%</small>}
    </li>)}</ul> : null}
    {adding === "link" ? <LinkForm onCancel={() => setAdding(null)} onSaved={(item) => { setItems((l) => [item, ...l]); setAdding(null); }} onError={setError} /> : null}
    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}

    <div className="libToolbar">
      <div className="studioTabs" role="tablist" aria-label="Seções">{SECTIONS.map((s) => <button key={s.key} type="button" role="tab" aria-selected={section === s.key}
        className={`studioTab${section === s.key ? " is-active" : ""}`} onClick={() => setSection(s.key)}>
        {s.label} <small>{s.key === "aprovados" ? approved.length : s.key === "materiais" ? items.length : items.length + approved.length}</small></button>)}</div>
      <input className="libSearch" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar" aria-label="Buscar na Biblioteca" />
    </div>
    {section !== "aprovados" ? <div className="libChips" aria-label="Categorias">
      <button type="button" className={`libChip${category === "todas" ? " is-on" : ""}`} onClick={() => setCategory("todas")}>Todas</button>
      {(Object.keys(LIBRARY_CATEGORIES) as LibraryCategory[]).map((c) => <button key={c} type="button" className={`libChip${category === c ? " is-on" : ""}`}
        onClick={() => setCategory(c)}>{LIBRARY_CATEGORIES[c]}{counts[c] ? <small>{counts[c]}</small> : null}</button>)}
    </div> : null}

    {loading && !items.length && !approved.length ? <p className="libHint">Carregando…</p> : null}
    {!loading && !shown.length ? <div className="libEmpty">
      {section === "aprovados" ? <p>Aprove posts no Calendário e a arte aparece aqui sozinha.</p>
        : <p>Nada aqui ainda. Envie um arquivo ou cole um link do Drive, Canva ou Figma.</p>}
    </div> : null}
    <ul className="libGrid" aria-label="Materiais">{shown.map((item) => <li key={item.id}>
      <button type="button" className="libCard" onClick={() => setViewing(item)} aria-label={`Abrir ${item.title}`}>
        <Thumb item={item} />
        <span className="libCardBody"><b>{item.title}</b>
          <small>{item.kind === "post" ? "Post aprovado" : LIBRARY_CATEGORIES[item.category as LibraryCategory] || "Outro"}
            {item.side === "cliente" ? " · do cliente" : ""}{item.size_bytes ? ` · ${formatBytes(item.size_bytes)}` : ""}</small></span>
      </button>
    </li>)}</ul>

    {viewing ? <Viewer item={viewing} onClose={() => setViewing(null)} onDelete={viewing.can_delete && viewing.kind !== "post" ? () => void remove(viewing) : undefined} /> : null}
  </div></Shell>;
}

function Thumb({ item }: { item: LibraryItem }) {
  const kind = previewKind(item);
  if (kind === "image") return <span className="libThumb"><img src={item.url} alt="" loading="lazy" /></span>;
  if (kind === "video") return <span className="libThumb"><video src={`${item.url}#t=0.5`} muted preload="metadata" /><i className="libBadge">Vídeo</i></span>;
  const label = kind === "pdf" ? "PDF" : kind === "link" ? (hostOf(item.url) || "Link") : (item.url.split(".").pop() || "Arquivo").toUpperCase().slice(0, 5);
  return <span className={`libThumb is-${kind}`}><span className="libThumbLabel">{label}</span></span>;
}

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function Viewer({ item, onClose, onDelete }: { item: LibraryItem; onClose: () => void; onDelete?: () => void }) {
  const kind = previewKind(item);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return <div className="libViewer" role="dialog" aria-modal="true" aria-label={item.title} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="libViewerBox">
      <header><div><b>{item.title}</b><small>{item.kind === "post" ? "Post aprovado no Calendário" : `${LIBRARY_CATEGORIES[item.category as LibraryCategory] || ""}${item.created_by_name ? ` · enviado por ${item.created_by_name}` : ""}`}</small></div>
        <button type="button" className="ds-button" onClick={onClose} aria-label="Fechar">Fechar</button></header>
      <div className="libViewerMedia">
        {kind === "image" ? <img src={item.url} alt={item.title} /> : kind === "video" ? <video src={item.url} controls /> :
          kind === "pdf" ? <iframe src={item.url} title={item.title} /> : <p className="libHint">Sem prévia. Abra em uma nova aba.</p>}
      </div>
      {item.note ? <p className="libNote">{item.note}</p> : null}
      <footer>
        <a className="ds-button is-primary" href={item.url} target="_blank" rel="noopener noreferrer">{item.kind === "link" ? "Abrir link" : "Baixar / abrir"}</a>
        {item.permalink ? <a className="ds-button" href={item.permalink} target="_blank" rel="noopener noreferrer">Ver no Instagram</a> : null}
        <button type="button" className="ds-button" onClick={() => { void navigator.clipboard?.writeText(item.url); }}>Copiar link</button>
        {onDelete ? <button type="button" className="ds-link libDelete" onClick={onDelete}>Apagar</button> : null}
      </footer>
    </div>
  </div>;
}

function LinkForm({ onCancel, onSaved, onError }: { onCancel: () => void; onSaved: (item: LibraryItem) => void; onError: (m: string | null) => void }) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<LibraryCategory>("referencia");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^https:\/\/\S+\.\S+/.test(url.trim());
  return <form className="libLinkForm" onSubmit={async (e) => {
    e.preventDefault(); setBusy(true); onError(null);
    try { onSaved((await addLibraryLink({ url: url.trim(), title: title.trim() || undefined, category, note: note.trim() || undefined })).item); }
    catch (cause) { onError(message(cause, "Não foi possível salvar o link.")); }
    finally { setBusy(false); }
  }}>
    <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://drive.google.com/…" aria-label="Link" autoFocus />
    <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Nome (opcional)" aria-label="Nome do link" />
    <select value={category} onChange={(e) => setCategory(e.target.value as LibraryCategory)} aria-label="Categoria">
      {(Object.keys(LIBRARY_CATEGORIES) as LibraryCategory[]).map((c) => <option key={c} value={c}>{LIBRARY_CATEGORIES[c]}</option>)}</select>
    <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Observação (opcional)" aria-label="Observação" />
    <button type="submit" className="ds-button is-primary" disabled={!valid || busy}>{busy ? "Salvando…" : "Salvar link"}</button>
    <button type="button" className="ds-button" onClick={onCancel}>Cancelar</button>
  </form>;
}
