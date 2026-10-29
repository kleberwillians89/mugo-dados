import { useEffect, useState } from "react";
import { ACCEPT, formatDuration, listAssets, uploadAsset, type StudioAsset } from "../../app/studioAssets";

type Props = {
  initial: StudioAsset[];
  max: number;
  onClose: () => void;
  onConfirm: (assets: StudioAsset[]) => Promise<void> | void;
};

/** Escolhe imagens/vídeos da Biblioteca na ordem dos slides; também envia arquivo novo. */
export default function ArtPicker({ initial, max, onClose, onConfirm }: Props) {
  const [library, setLibrary] = useState<StudioAsset[] | null>(null);
  const [selected, setSelected] = useState<StudioAsset[]>(initial);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<{ name: string; progress: number } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    listAssets().then((d) => setLibrary(d.assets.filter((a) => a.kind !== "pdf")))
      .catch((e) => setError(e instanceof Error ? e.message : "Não foi possível abrir a Biblioteca."));
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !saving) { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose, saving]);

  const order = (id: string) => selected.findIndex((a) => a.id === id);
  function toggle(asset: StudioAsset) {
    setError(null);
    if (order(asset.id) >= 0) setSelected(selected.filter((a) => a.id !== asset.id));
    else if (selected.length >= max) setError(`No máximo ${max} mídias por pauta.`);
    else setSelected([...selected, asset]);
  }

  async function upload(files: FileList | null) {
    for (const file of Array.from(files || [])) {
      setUploading({ name: file.name, progress: 0 }); setError(null);
      try {
        const asset = await uploadAsset(file, {}, (progress) => setUploading({ name: file.name, progress }));
        if (asset.kind === "pdf") { setError("PDF foi para a Biblioteca, mas não entra na pauta."); continue; }
        setLibrary((all) => [asset, ...(all || [])]);
        setSelected((all) => (all.length < max ? [...all, asset] : all));
      } catch (e) { setError(e instanceof Error ? e.message : "O envio falhou."); }
    }
    setUploading(null);
  }

  async function confirm() {
    setSaving(true);
    try { await onConfirm(selected); } finally { setSaving(false); }
  }

  return <div className="artPickerBackdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !saving) onClose(); }}>
    <div className="artPicker" role="dialog" aria-modal="true" aria-label="Escolher arte da Biblioteca">
      <header><h3>Arte da pauta</h3><p>Clique na ordem dos slides. {selected.length}/{max}</p></header>
      <div className="artPickerUpload">
        <label className="ds-button">Enviar arquivo<input type="file" accept={ACCEPT} multiple hidden disabled={Boolean(uploading)} onChange={(e) => { void upload(e.target.files); e.currentTarget.value = ""; }} /></label>
        {uploading ? <span className="libProgress"><span style={{ width: `${Math.round(uploading.progress * 100)}%` }} /><em>{uploading.name} · {Math.round(uploading.progress * 100)}%</em></span> : null}
      </div>
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      {!library ? <p>Carregando Biblioteca…</p> : !library.length ? <p className="studioEmpty">A Biblioteca ainda está vazia. Envie a primeira arte.</p> :
        <ul className="libGrid is-picker">{library.map((asset) => {
          const n = order(asset.id);
          return <li key={asset.id}><button type="button" className={`libCard ${n >= 0 ? "is-selected" : ""}`} aria-pressed={n >= 0} onClick={() => toggle(asset)}>
            <span className="libThumb">{asset.thumb_url ? <img src={asset.thumb_url} alt="" loading="lazy" /> : <b>{asset.kind === "video" ? "▶" : "▢"}</b>}
              {asset.kind === "video" ? <i className="libBadge">▶ {formatDuration(asset.duration_seconds)}</i> : null}
              {n >= 0 ? <i className="libOrder">{n + 1}</i> : null}</span>
            <span className="libName">{asset.name}</span>
          </button></li>;
        })}</ul>}
      <footer className="studioActions">
        <button type="button" className="ds-button" onClick={onClose} disabled={saving}>Cancelar</button>
        <button type="button" className="ds-button is-primary" onClick={() => void confirm()} disabled={saving || Boolean(uploading)}>{saving ? "Salvando…" : "Usar na pauta"}</button>
      </footer>
    </div>
  </div>;
}
