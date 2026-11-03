import { useState, type ChangeEvent } from "react";
import Drawer from "../Drawer";
import { STUDIO_FORMATS, commitCalendarImport, parseCalendarImport, type ImportRow, type StudioFormat } from "../../app/studio";
import { extractSlides, slidesFromText, type SlideText } from "../../app/pptxSlides";
import ArtLink from "./ArtLink";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const MAX_BYTES = 80 * 1024 * 1024;

/**
 * Importar um calendário pronto: o PowerPoint é lido aqui no navegador (só texto e links seguem para a IA),
 * a equipe revisa cada linha e escolhe se entra como já aprovado pelo cliente ou como rascunho.
 */
export default function ImportCalendar({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (summary: string) => void }) {
  const [rows, setRows] = useState<(ImportRow & { keep: boolean })[] | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [pasted, setPasted] = useState("");
  const [approved, setApproved] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function reset() { setRows(null); setNotes([]); setPasted(""); setError(null); setApproved(true); }

  async function read(slides: SlideText[], name: string) {
    if (!slides.length) { setError("Não encontrei texto nos slides."); return; }
    setBusy("parse"); setError(null);
    try {
      const out = await parseCalendarImport(slides, name);
      setRows(out.items.map((r) => ({ ...r, keep: Boolean(r.date) })));
      setNotes([`${out.slides} slide(s) lidos, ${out.items.length} post(s) encontrados.`, ...out.notes]);
    } catch (cause) { setError(message(cause, "Não foi possível ler o calendário agora.")); }
    finally { setBusy(null); }
  }

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!/\.pptx$/i.test(file.name)) { setError("Envie o arquivo .pptx (no Google Slides ou no Canva: Baixar → PowerPoint)."); return; }
    if (file.size > MAX_BYTES) { setError("Arquivo acima de 80 MB. Exporte sem vídeos ou cole o texto."); return; }
    setBusy("file"); setError(null);
    try { await read(extractSlides(new Uint8Array(await file.arrayBuffer())), file.name); }
    catch (cause) { setError(message(cause, "Não consegui abrir o arquivo.")); setBusy(null); }
  }

  const set = (i: number, patch: Partial<ImportRow & { keep: boolean }>) => setRows((r) => r && r.map((row, j) => (j === i ? { ...row, ...patch } : row)));
  const chosen = (rows || []).filter((r) => r.keep);
  const missingDate = chosen.some((r) => !r.date);

  async function commit() {
    if (!chosen.length || missingDate) return;
    setBusy("commit"); setError(null);
    try {
      const out = await commitCalendarImport(chosen, approved);
      const parts = [`${out.created} post(s) importado(s)${out.approved ? " como aprovados" : " como rascunho"}`,
        out.skipped_duplicates ? `${out.skipped_duplicates} já existiam` : "", out.invalid ? `${out.invalid} sem data válida` : ""].filter(Boolean);
      onDone(parts.join(", ") + ".");
      reset();
    } catch (cause) { setError(message(cause, "Não foi possível importar.")); }
    finally { setBusy(null); }
  }

  return <Drawer open={open} width="lg" title="Importar calendário" description="Suba o PowerPoint do calendário (com os links da arte). A IA organiza os posts; você revisa antes de entrar."
    onClose={() => { if (!busy) { reset(); onClose(); } }}>
    <div className="studioForm importCal">
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      {!rows ? <>
        <label className="importDrop">
          <strong>{busy ? "Lendo os slides… (até 2 min)" : "Escolher o arquivo .pptx"}</strong>
          <span>PowerPoint, Google Slides ou Canva exportado como PowerPoint. O arquivo não sai do seu computador: só o texto e os links.</span>
          <input type="file" accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation" disabled={Boolean(busy)} onChange={(e) => void onFile(e)} />
        </label>
        <details><summary>Ou cole o texto do calendário</summary>
          <textarea rows={8} value={pasted} placeholder={"05/11 18h Reels: Vinho laranja\nLegenda…\nArte: https://www.canva.com/…\n\n07/11 …"} onChange={(e) => setPasted(e.target.value)} />
          <button type="button" className="ds-button" disabled={Boolean(busy) || !pasted.trim()} onClick={() => void read(slidesFromText(pasted), "texto colado")}>Ler texto</button>
        </details>
      </> : <>
        {notes.length ? <ul className="aiList">{notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
        <fieldset className="importMode"><legend>Como entram no Calendário</legend>
          <label className="studioCheck"><input type="radio" checked={approved} onChange={() => setApproved(true)} /> Já aprovados pelo cliente (não vão para aprovação)</label>
          <label className="studioCheck"><input type="radio" checked={!approved} onChange={() => setApproved(false)} /> Rascunho (a equipe revisa e envia para aprovação)</label>
        </fieldset>
        <ol className="importRows">{rows.map((r, i) => <li key={i} className={r.keep ? "" : "is-off"}>
          <label className="studioCheck"><input type="checkbox" checked={r.keep} onChange={(e) => set(i, { keep: e.target.checked })} /> Importar{r.slide ? ` (slide ${r.slide})` : ""}</label>
          <div className="studioRow">
            <label>Data<input type="date" value={r.date} required={r.keep} onChange={(e) => set(i, { date: e.target.value })} /></label>
            <label>Horário<input type="time" value={r.time} placeholder="10:00" onChange={(e) => set(i, { time: e.target.value })} /></label>
            <label>Formato<select value={r.format} onChange={(e) => set(i, { format: e.target.value as StudioFormat })}>
              {Object.entries(STUDIO_FORMATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          </div>
          <label>Pauta<input maxLength={200} value={r.title} onChange={(e) => set(i, { title: e.target.value })} /></label>
          <label>Legenda<textarea rows={3} maxLength={4000} value={r.caption} onChange={(e) => set(i, { caption: e.target.value })} /></label>
          <label>Link da arte<input type="url" maxLength={1000} value={r.art_url} placeholder="https://…" onChange={(e) => set(i, { art_url: e.target.value })} /></label>
          {r.art_url.startsWith("https://") ? <ArtLink url={r.art_url} preview={false} /> : null}
          {r.issues?.length ? <p className="clipWarn">Conferir: {r.issues.join(", ")}.</p> : null}
        </li>)}</ol>
        <div className="studioActions importFooter">
          <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={reset}>Começar de novo</button>
          <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !chosen.length || missingDate} onClick={() => void commit()}>
            {busy === "commit" ? "Importando…" : `Importar ${chosen.length} post(s)`}</button>
        </div>
        {missingDate ? <p className="clipWarn">Preencha a data dos posts marcados (ou desmarque).</p> : null}
        <p className="libHint">Sem horário, o post entra às 10h. Repetir a importação não duplica posts com a mesma data, hora e pauta.</p>
      </>}
    </div>
  </Drawer>;
}
