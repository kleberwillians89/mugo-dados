import { useState, type FormEvent } from "react";
import { LIBRARY_CATEGORIES, formatBytes, importLibraryCloud, listLibraryCloud, type LibraryCategory, type LibraryCloudFile, type LibraryItem } from "../../app/library";

type Row = LibraryCloudFile & { pick: boolean; known: boolean; status?: "copiando" | "ok" | "erro"; note?: string };

/**
 * Importar do Google Drive (pasta com subpastas, ou arquivo) ou do Canva para a Biblioteca: fotos, vídeos, logos,
 * PDFs e documentos vão direto do Drive para a pasta da empresa, já com a categoria sugerida (dá para trocar).
 */
export default function LibraryCloudImport({ knownTitles, onAdded, onClose }: {
  knownTitles: string[]; onAdded: (item: LibraryItem) => void; onClose: () => void;
}) {
  const [url, setUrl] = useState("");
  const [source, setSource] = useState<"drive" | "canva">("drive");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [busy, setBusy] = useState<"list" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function list(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    const known = new Set(knownTitles.map((t) => t.toLowerCase()));
    setBusy("list"); setError(null); setRows(null);
    try {
      const res = await listLibraryCloud(url.trim());
      setSource(res.source); setTruncated(res.truncated);
      setRows(res.files.map((f) => {
        const already = known.has(f.name.toLowerCase());
        return { ...f, known: already, pick: f.supported && !already };
      }));
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não consegui abrir esse link.");
    } finally { setBusy(null); }
  }

  const update = (id: string, patch: Partial<Row>) => setRows((all) => all && all.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const toggleAll = (pick: boolean) => setRows((all) => all && all.map((r) => (r.supported && r.status !== "ok" ? { ...r, pick } : r)));

  async function importPicked() {
    const picked = (rows || []).filter((r) => r.pick && r.supported && r.status !== "ok");
    setBusy("import"); setError(null);
    for (const row of picked) {
      update(row.id, { status: "copiando", note: undefined });
      try {
        const { item } = await importLibraryCloud(source, row, row.category);
        onAdded(item);
        update(row.id, { status: "ok", pick: false });
      } catch (cause) {
        update(row.id, { status: "erro", note: cause instanceof Error && cause.message ? cause.message : "Não foi possível copiar." });
      }
    }
    setBusy(null);
  }

  const picked = (rows || []).filter((r) => r.pick && r.supported && r.status !== "ok").length;
  const done = (rows || []).filter((r) => r.status === "ok").length;
  return <section className="libCloud" aria-label="Importar do Google Drive ou do Canva">
    <form className="libCloudRow" onSubmit={list}>
      <label className="libCloudField">Link da pasta do Google Drive, de um arquivo ou de um design do Canva
        <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://drive.google.com/drive/folders/…" required /></label>
      <button type="submit" className="ds-button is-primary" disabled={Boolean(busy)}>{busy === "list" ? "Abrindo…" : "Ver arquivos"}</button>
      <button type="button" className="ds-button" disabled={busy === "import"} onClick={onClose}>Fechar</button>
    </form>
    <small className="libHint">No Drive, compartilhe a pasta como “Qualquer pessoa com o link pode ver”. Do Canva entra a imagem de prévia; para a arte em qualidade máxima, baixe no Canva e envie o arquivo.</small>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {rows ? <>
      {rows.some((r) => r.supported) ? <div className="libCloudRow">
        <button type="button" className="ds-link" onClick={() => toggleAll(true)}>Marcar tudo</button>
        <button type="button" className="ds-link" onClick={() => toggleAll(false)}>Desmarcar tudo</button>
      </div> : null}
      {rows.length ? <ul className="libCloudList">{rows.map((r) => <li key={r.id} className={r.supported ? "" : "is-off"}>
        <label className="libCloudPick">
          <input type="checkbox" checked={r.pick} disabled={!r.supported || busy === "import" || r.status === "ok"}
            onChange={(e) => update(r.id, { pick: e.target.checked })} />
          <span className="libCloudName"><b>{r.path}{r.name}</b>
            <small>{[r.size ? formatBytes(r.size) : null, r.known ? "já está na Biblioteca" : null, r.reason].filter(Boolean).join(" · ")}</small></span>
        </label>
        {r.supported ? <label className="libCloudCat"><span className="ds-srOnly">Categoria de {r.name}</span>
          <select value={r.category} disabled={busy === "import" || r.status === "ok"} onChange={(e) => update(r.id, { category: e.target.value as LibraryCategory })}>
            {(Object.keys(LIBRARY_CATEGORIES) as LibraryCategory[]).map((k) => <option key={k} value={k}>{LIBRARY_CATEGORIES[k]}</option>)}</select></label> : null}
        {r.status ? <span className={`libCloudState is-${r.status}`} role={r.status === "erro" ? "alert" : "status"}>
          {r.status === "copiando" ? "Copiando…" : r.status === "ok" ? "Na Biblioteca" : "Erro"}</span> : null}
        {r.note ? <small className="libCloudNote">{r.note}</small> : null}
      </li>)}</ul> : <p className="libHint">Essa pasta está vazia.</p>}
      {truncated ? <small className="libHint">Mostrando os primeiros 100 arquivos (até 3 níveis de subpasta).</small> : null}
      <div className="libCloudRow">
        <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !picked} onClick={() => void importPicked()}>
          {busy === "import" ? `Copiando… ${done} de ${done + picked}` : `Importar ${picked} arquivo${picked === 1 ? "" : "s"}`}</button>
        <small className="libHint">Vídeos grandes levam alguns minutos.</small>
      </div>
    </> : null}
  </section>;
}
