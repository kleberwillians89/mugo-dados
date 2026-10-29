import { useCallback, useEffect, useState, type DragEvent, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  ACCEPT, ASSET_KINDS, deleteAsset, formatBytes, formatDuration, listAssets, updateAsset, uploadAsset,
  type AssetKind, type AssetLibrary, type StudioAsset,
} from "../app/studioAssets";
import { listToText, textToList } from "../app/studio";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import Drawer from "../components/Drawer";
import "../styles/studio.css";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const KIND_TABS: Record<AssetKind, string> = { imagem: "Imagens", video: "Vídeos", pdf: "PDFs" };
type Upload = { key: string; name: string; progress: number; error?: string };
type Filters = { kind?: AssetKind; folder?: string; tag?: string; q?: string };

/** Biblioteca do Studio: artes, vídeos e PDFs da marca, por pasta e tag. */
export default function Library({ canManage }: { canManage: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const [data, setData] = useState<AssetLibrary | null>(null);
  const [filters, setFilters] = useState<Filters>({});
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [dragging, setDragging] = useState(false);
  const [open, setOpen] = useState<StudioAsset | null>(null);
  const [edit, setEdit] = useState<{ name: string; folder: string; tags: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const result = await listAssets(filters);
      if (getActiveClientId() === clientId) setData(result);
    } catch (cause) { setError(message(cause, "Não foi possível carregar a Biblioteca.")); }
    finally { setLoading(false); }
  }, [filters, clientId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const t = window.setTimeout(() => setFilters((f) => (f.q === (search.trim() || undefined) ? f : { ...f, q: search.trim() || undefined })), 300);
    return () => window.clearTimeout(t);
  }, [search]);

  async function send(files: FileList | File[] | null) {
    const list = Array.from(files || []);
    if (!list.length || !canManage) return;
    const batch = list.map((file, i) => ({ file, key: `${Date.now()}-${i}-${file.name}` }));
    setUploads((all) => [...all, ...batch.map(({ file, key }) => ({ key, name: file.name, progress: 0 }))]);
    const patch = (key: string, value: Partial<Upload>) => setUploads((all) => all.map((u) => (u.key === key ? { ...u, ...value } : u)));
    // Um por vez: no celular, envios paralelos de vídeo competem pela mesma conexão.
    for (const { file, key } of batch) {
      try {
        await uploadAsset(file, { folder: filters.folder, tags: filters.tag ? [filters.tag] : [] }, (progress) => patch(key, { progress }));
        setUploads((all) => all.filter((u) => u.key !== key));
      } catch (cause) { patch(key, { error: message(cause, "O envio falhou.") }); }
    }
    await load();
  }

  function onDrop(e: DragEvent) {
    e.preventDefault(); setDragging(false);
    void send(e.dataTransfer.files);
  }

  function openAsset(asset: StudioAsset) {
    setError(null); setOpen(asset);
    setEdit({ name: asset.name || "", folder: asset.folder || "", tags: listToText(asset.tags) });
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!open || !edit || busy) return;
    setBusy(true); setError(null);
    try {
      await updateAsset(open.id, { name: edit.name, folder: edit.folder.trim() || null, tags: textToList(edit.tags) });
      setOpen(null); await load();
    } catch (cause) { setError(message(cause, "Não foi possível salvar.")); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!open || busy) return;
    const used = open.used_in ? ` Ele está em ${open.used_in} pauta(s) e sai delas também.` : "";
    if (!window.confirm(`Excluir “${open.name}” da Biblioteca?${used}`)) return;
    setBusy(true); setError(null);
    try { await deleteAsset(open.id); setOpen(null); await load(); }
    catch (cause) { setError(message(cause, "Não foi possível excluir.")); }
    finally { setBusy(false); }
  }

  const assets = data?.assets || [];
  const hasFilter = Boolean(filters.kind || filters.folder || filters.tag || filters.q);

  return <Shell title="Biblioteca" variant="editorial"><div className={`ds-page studioPage libPage ${dragging ? "is-dragging" : ""}`}
    onDragOver={canManage ? (e) => { e.preventDefault(); setDragging(true); } : undefined}
    onDragLeave={canManage ? (e) => { if (e.currentTarget === e.target) setDragging(false); } : undefined}
    onDrop={canManage ? onDrop : undefined}>
    <PageHeader company={clientName} title="Biblioteca" controls={canManage ? <div className="studioControls">
      <label className="ds-button is-primary">Enviar arquivos<input type="file" accept={ACCEPT} multiple hidden onChange={(e) => { void send(e.target.files); e.currentTarget.value = ""; }} /></label>
    </div> : undefined} />
    <p className="libHint">Imagem até 15 MB, vídeo até 200 MB, PDF até 30 MB. {canManage ? "Arraste arquivos para cá" : ""}{canManage && filters.folder ? ` · vão para a pasta “${filters.folder}”` : ""}.</p>

    <div className="libToolbar">
      <div className="studioTabs" role="tablist" aria-label="Tipo">
        {([undefined, "imagem", "video", "pdf"] as const).map((kind) => <button key={kind || "todos"} role="tab" aria-selected={filters.kind === kind}
          className={filters.kind === kind ? "is-active" : ""} onClick={() => setFilters({ ...filters, kind })}>{kind ? KIND_TABS[kind] : "Todos"}</button>)}
      </div>
      <label>Pasta<select value={filters.folder || ""} onChange={(e) => setFilters({ ...filters, folder: e.target.value || undefined })}>
        <option value="">Todas</option>{(data?.folders || []).map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
      <label>Tag<select value={filters.tag || ""} onChange={(e) => setFilters({ ...filters, tag: e.target.value || undefined })}>
        <option value="">Todas</option>{(data?.tags || []).map((t) => <option key={t} value={t}>#{t}</option>)}</select></label>
      <label className="libSearch">Buscar<input type="search" value={search} maxLength={80} placeholder="Nome do arquivo" onChange={(e) => setSearch(e.target.value)} /></label>
    </div>

    {uploads.length ? <ul className="libUploads" aria-live="polite">{uploads.map((u) => <li key={u.key} className={u.error ? "is-error" : ""}>
      <span className="libUploadName">{u.name}</span>
      {u.error ? <><span role="alert">{u.error}</span><button type="button" className="studioLink" onClick={() => setUploads((all) => all.filter((x) => x.key !== u.key))}>Dispensar</button></>
        : <span className="libProgress"><span style={{ width: `${Math.round(u.progress * 100)}%` }} /><em>{Math.round(u.progress * 100)}%</em></span>}
    </li>)}</ul> : null}

    {error && !open ? <p role="alert" className="studioError">{error}</p> : null}
    {loading && !data ? <p>Carregando Biblioteca…</p> : null}
    {!loading && data && !assets.length ? <div className="studioEmpty">
      <p>{hasFilter ? "Nenhum arquivo com esses filtros." : "A Biblioteca ainda está vazia."}</p>
      {canManage && !hasFilter ? <p>Envie artes, vídeos e PDFs da marca. Depois é só anexar na pauta pelo <b>Calendário</b>.</p> : null}
    </div> : null}

    <ul className="libGrid">{assets.map((asset) => <li key={asset.id}>
      <button type="button" className="libCard" onClick={() => openAsset(asset)}>
        <span className="libThumb">{asset.thumb_url ? <img src={asset.thumb_url} alt="" loading="lazy" /> : <b>{asset.kind === "pdf" ? "PDF" : asset.kind === "video" ? "▶" : "▢"}</b>}
          {asset.kind === "video" ? <i className="libBadge">▶ {formatDuration(asset.duration_seconds)}</i> : null}</span>
        <span className="libName">{asset.name}</span>
        <span className="libMeta">{ASSET_KINDS[asset.kind]} · {formatBytes(asset.size_bytes)}{asset.width && asset.height ? ` · ${asset.width}×${asset.height}` : ""}</span>
        {asset.folder || asset.used_in ? <span className="libMeta">{asset.folder ? `📁 ${asset.folder}` : ""}{asset.folder && asset.used_in ? " · " : ""}{asset.used_in ? `em ${asset.used_in} pauta(s)` : ""}</span> : null}
      </button>
    </li>)}</ul>

    <Drawer open={Boolean(open)} title={open?.name || "Arquivo"} description={open ? `${ASSET_KINDS[open.kind]} · ${formatBytes(open.size_bytes)}${open.used_in ? ` · em ${open.used_in} pauta(s)` : ""}` : undefined}
      width="lg" onClose={() => { if (!busy) setOpen(null); }}>
      {open ? <div className="studioForm">
        <div className="libPreview">
          {open.kind === "imagem" && open.url ? <img src={open.url} alt={open.name || ""} /> : null}
          {open.kind === "video" && open.url ? <video src={open.url} poster={open.thumb_url || undefined} controls playsInline preload="metadata" /> : null}
          {open.kind === "pdf" && open.url ? <a className="ds-button" href={open.url} target="_blank" rel="noreferrer noopener">Abrir PDF ↗</a> : null}
          {!open.url ? <p className="studioError">Não foi possível gerar o link do arquivo agora.</p> : null}
        </div>
        {canManage && edit ? <form className="studioForm" onSubmit={save}>
          <label>Nome<input required maxLength={160} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
          <label>Pasta<input list="lib-folders" maxLength={80} value={edit.folder} placeholder="Sem pasta" onChange={(e) => setEdit({ ...edit, folder: e.target.value })} />
            <datalist id="lib-folders">{(data?.folders || []).map((f) => <option key={f} value={f} />)}</datalist></label>
          <label>Tags (separe por vírgula)<input value={edit.tags} onChange={(e) => setEdit({ ...edit, tags: e.target.value })} placeholder="natal, produto, lifestyle" /></label>
          {error ? <p role="alert" className="studioError">{error}</p> : null}
          <div className="studioActions">
            <button type="button" className="studioLink" disabled={busy} onClick={() => void remove()}>Excluir</button>
            <button type="button" className="ds-button" onClick={() => setOpen(null)} disabled={busy}>Cancelar</button>
            <button className="ds-button is-primary" disabled={busy}>{busy ? "Salvando…" : "Salvar"}</button>
          </div>
        </form> : <p>{open.folder ? `Pasta: ${open.folder}. ` : ""}{open.tags?.length ? `Tags: ${open.tags.map((t) => `#${t}`).join(" ")}` : ""}</p>}
      </div> : null}
    </Drawer>
  </div></Shell>;
}
