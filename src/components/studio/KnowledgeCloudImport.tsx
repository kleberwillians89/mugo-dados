import { useState, type FormEvent } from "react";
import { needsOcr, teachAndKeepOriginal, type TeachWithOriginal } from "../../app/brandKnowledgeUpload";
import { fetchCloudImport, listCloudImport, type CloudFile, type KnowledgeKind } from "../../app/studio";

type Row = CloudFile & { pick: boolean; known: boolean; status?: "lendo" | "ok" | "aviso" | "erro"; note?: string };

function toFile(name: string, mime: string, b64: string) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new File([bytes], name, { type: mime });
}
const sizeLabel = (n: number | null) => (n == null ? "" : n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

/**
 * Importar do Google Drive ou do Canva: cola o link da pasta (ou do arquivo, ou do design), marca o que entra e cada
 * arquivo segue o envio de sempre (o texto ensina a IA, o original vai para a Biblioteca, PDF escaneado é lido pela IA).
 */
export default function KnowledgeCloudImport({ kind, knownNames, onLearned, onClose }: {
  kind: KnowledgeKind; knownNames: string[]; onLearned: (res: TeachWithOriginal) => void; onClose: () => void;
}) {
  const [url, setUrl] = useState("");
  const [source, setSource] = useState<"drive" | "canva">("drive");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [busy, setBusy] = useState<"list" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const known = new Set(knownNames.map((n) => n.toLowerCase()));

  async function list(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    setBusy("list"); setError(null); setRows(null);
    try {
      const res = await listCloudImport(url.trim());
      setSource(res.source); setTruncated(res.truncated);
      setRows(res.files.map((f) => {
        const already = [...known].some((k) => k.startsWith(f.name.toLowerCase().replace(/\.[a-z0-9]+$/, "")));
        return { ...f, known: already, pick: f.supported && !already };
      }));
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não consegui abrir esse link.");
    } finally { setBusy(null); }
  }

  const update = (id: string, patch: Partial<Row>) => setRows((all) => all && all.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  async function importPicked() {
    const picked = (rows || []).filter((r) => r.pick && r.supported && r.status !== "ok");
    setBusy("import"); setError(null);
    for (const row of picked) {
      update(row.id, { status: "lendo", note: undefined });
      try {
        const got = await fetchCloudImport(source, row);
        const file = toFile(got.file_name, got.mime, got.content_base64);
        let res: TeachWithOriginal;
        try {
          res = await teachAndKeepOriginal(file, kind, got.needs_ocr ? { ocr: true } : {});
        } catch (cause) {
          if (!needsOcr(cause)) throw cause;
          update(row.id, { note: "PDF sem texto: a IA está lendo as páginas…" });
          res = await teachAndKeepOriginal(file, kind, { ocr: true });
        }
        onLearned(res);
        update(row.id, res.warning ? { status: "aviso", note: res.warning } : { status: "ok", note: res.document.summary || "Aprendido." });
      } catch (cause) {
        update(row.id, { status: "erro", note: cause instanceof Error && cause.message ? cause.message : "Não foi possível importar." });
      }
    }
    setBusy(null);
  }

  const picked = (rows || []).filter((r) => r.pick && r.supported && r.status !== "ok").length;
  const done = (rows || []).filter((r) => r.status === "ok" || r.status === "aviso").length;
  return <div className="kbCloud">
    <form className="kbRow" onSubmit={list}>
      <label className="kbCloudField">Link da pasta do Google Drive, de um arquivo ou de um design do Canva
        <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://drive.google.com/drive/folders/…" required /></label>
      <button type="submit" className="ds-button is-primary" disabled={Boolean(busy)}>{busy === "list" ? "Abrindo…" : "Ver arquivos"}</button>
      <button type="button" className="ds-button" disabled={busy === "import"} onClick={onClose}>Fechar</button>
    </form>
    <small className="libHint">No Drive, compartilhe a pasta como “Qualquer pessoa com o link pode ver”. No Canva, use o link de visualização: entra a primeira página (para um design longo, exporte em PDF e coloque no Drive).</small>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {rows ? <>
      {rows.length ? <ul className="kbCloudList">{rows.map((r) => <li key={r.id} className={r.supported ? "" : "is-off"}>
        <label>
          <input type="checkbox" checked={r.pick} disabled={!r.supported || busy === "import" || r.status === "ok"} onChange={(e) => update(r.id, { pick: e.target.checked })} />
          <span className="kbCloudName"><b>{r.path}{r.name}</b>
            <small>{[sizeLabel(r.size), r.known ? "já está no Conhecimento" : null, r.reason].filter(Boolean).join(" · ")}</small></span>
        </label>
        {r.status ? <span className={`kbCloudState is-${r.status}`} role={r.status === "erro" ? "alert" : "status"}>
          {r.status === "lendo" ? (r.note || "Lendo…") : r.status === "ok" ? "Aprendido" : r.status === "aviso" ? "Guardado com aviso" : "Erro"}</span> : null}
        {r.note && r.status !== "lendo" ? <small className="kbCloudNote">{r.note}</small> : null}
      </li>)}</ul> : <p className="libHint">Essa pasta está vazia.</p>}
      {truncated ? <small className="libHint">Mostrando os primeiros 100 arquivos (até 3 níveis de subpasta).</small> : null}
      <div className="kbRow">
        <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !picked} onClick={() => void importPicked()}>
          {busy === "import" ? `Importando… ${done} de ${done + picked}` : `Importar ${picked} arquivo${picked === 1 ? "" : "s"}`}</button>
        <small className="libHint">Cada arquivo leva até 1 minuto. Pode continuar usando a plataforma em outra aba.</small>
      </div>
    </> : null}
  </div>;
}
