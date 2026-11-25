import { useEffect, useRef, useState, type DragEvent } from "react";
import { ExternalLink, FileText, FolderDown, MessageSquare, Pencil, RotateCw, ScanText, Sparkles, Type, UploadCloud } from "lucide-react";
import KnowledgeCloudImport from "./KnowledgeCloudImport";
import { needsOcr, originalsByDocument, teachAndKeepOriginal, type TeachWithOriginal } from "../../app/brandKnowledgeUpload";
import { getKnowledge, learnFromLibrary, retryKnowledgeDocument, saveKnowledge, teachFromText, type BrandKnowledge as Knowledge, type KnowledgeKind, type TeachResult } from "../../app/studio";
import { parseKnowledge } from "./brandKnowledge.helpers";

const KINDS: Record<KnowledgeKind, string> = { institucional: "Institucional", produto: "Produtos e preços", campanha: "Campanha",
  tom_de_voz: "Tom de voz", restricao: "Restrições", outro: "Outro", conversa: "Conversa" };
const UPLOAD_KINDS = (Object.keys(KINDS) as KnowledgeKind[]).filter((k) => k !== "conversa");
const ACCEPT = ".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md";
const MAX = 6000;
const when = (iso: string) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });


/** Complemento da mensagem de sucesso: páginas lidas pela IA e original guardado na Biblioteca. */
function describeUpload(res: Partial<TeachWithOriginal>): string {
  const parts: string[] = [];
  if (res.ocr) parts.push(` A IA leu ${res.ocr.pages_read} de ${res.ocr.pages_total} página(s)${res.ocr.pages_total > res.ocr.pages_limit ? ` (limite de ${res.ocr.pages_limit} por envio)` : ""}.`);
  if (res.original === "guardado") parts.push(" O arquivo original ficou na Biblioteca.");
  if (res.original === "nao_guardado") parts.push(" O original não pôde ir para a Biblioteca; o texto ficou guardado.");
  return parts.join("");
}

/**
 * Marca & IA → Conhecimento. À esquerda, ensinar (arrastar arquivos ou colar texto); à direita, o que a IA já sabe.
 * O conteúdo de cada material fica guardado antes de a IA ler: se a IA falhar, dá para tentar de novo sem reenviar.
 * ``version`` muda quando outra parte da tela (o agente) altera a memória: recarrega.
 */
export default function BrandKnowledge({ canManage, version = 0 }: { canManage: boolean; version?: number }) {
  const [data, setData] = useState<Knowledge | null>(null);
  const [kind, setKind] = useState<KnowledgeKind>("institucional");
  const [text, setText] = useState("");
  const [pasting, setPasting] = useState(false);
  const [cloud, setCloud] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [warn, setWarn] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  // PDF sem texto: a pessoa decide se a IA lê as páginas (custa uma leitura por página).
  const [ocrFile, setOcrFile] = useState<File | null>(null);
  const [originals, setOriginals] = useState<Record<string, string>>({});
  const input = useRef<HTMLInputElement>(null);
  const [library, setLibrary] = useState<string | null>(null);

  useEffect(() => {
    getKnowledge().then(setData).catch(() => setData({ knowledge: "", sources: 0, updated_at: null, documents: [] }));
    void originalsByDocument().then(setOriginals);
  }, [version]);

  // A IA lê sozinha os documentos novos da Biblioteca (sem enviar duas vezes). Até 3 rodadas de 4 arquivos.
  useEffect(() => {
    if (!canManage) return;
    let alive = true;
    void (async () => {
      const read: string[] = []; const skipped: string[] = [];
      for (let round = 0; round < 3 && alive; round += 1) {
        if (round === 0) setLibrary("Lendo os documentos da Biblioteca…");
        let res;
        try { res = await learnFromLibrary(); } catch { break; }
        read.push(...res.read.map((r) => r.name)); skipped.push(...res.skipped.map((r) => `${r.name} (${r.reason})`));
        if (res.running || !res.left || !res.read.length) break;
      }
      if (!alive) return;
      setLibrary(read.length || skipped.length ? [read.length ? `Li da Biblioteca: ${read.join(", ")}.` : "",
        skipped.length ? `Não deu para ler: ${skipped.join(", ")}.` : ""].filter(Boolean).join(" ") : null);
      if (read.length) getKnowledge().then((d) => { if (alive) setData(d); }).catch(() => undefined);
    })();
    return () => { alive = false; };
  }, [canManage, version]);

  async function run(label: string, task: () => Promise<TeachResult>) {
    setBusy(label); setError(null); setOk(null); setWarn(null);
    try {
      const res = await task();
      setData((d) => ({ knowledge: res.knowledge, sources: res.sources, updated_at: new Date().toISOString(),
        documents: [res.document, ...(d?.documents || []).filter((x) => x.id !== res.document.id)] }));
      const extra = describeUpload(res as Partial<TeachWithOriginal>);
      if (res.warning) setWarn(`“${res.document.name}”: ${res.warning}${extra}`);
      else setOk((res.document.summary ? `Aprendi com “${res.document.name}”: ${res.document.summary}` : `Aprendi com “${res.document.name}”.`) + extra);
      const kept = res as Partial<TeachWithOriginal>;
      if (kept.original === "guardado") void originalsByDocument().then(setOriginals);
      return true;
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível processar."); return false; }
    finally { setBusy(null); }
  }
  async function onFiles(files: FileList | File[] | null) {
    setOcrFile(null);
    for (const file of Array.from(files || [])) {
      setBusy(file.name); setError(null); setOk(null); setWarn(null);
      try {
        const res = await teachAndKeepOriginal(file, kind);
        setBusy(null);
        await run(file.name, async () => res);
      } catch (cause) {
        setBusy(null);
        if (needsOcr(cause)) { setOcrFile(file); setWarn(cause instanceof Error ? cause.message : "Este PDF não tem texto selecionável."); }
        else setError(cause instanceof Error ? cause.message : "Não foi possível processar.");
      }
    }
    if (input.current) input.current.value = "";
  }
  async function readWithOcr() {
    const file = ocrFile;
    if (!file) return;
    setOcrFile(null);
    await run(file.name, () => teachAndKeepOriginal(file, kind, { ocr: true }));
  }
  function onDrop(event: DragEvent) { event.preventDefault(); setDrag(false); if (canManage && !busy) void onFiles(event.dataTransfer.files); }
  async function saveEdit() {
    if (editing === null) return;
    setBusy("edit"); setError(null);
    try { const res = await saveKnowledge(editing); setData((d) => d && { ...d, knowledge: res.knowledge }); setEditing(null); setOk("Conhecimento atualizado."); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar."); }
    finally { setBusy(null); }
  }

  if (!data) return <p className="libHint">Carregando…</p>;
  const sectionsList = parseKnowledge(data.knowledge);
  const used = Math.min(100, Math.round((data.knowledge.length / MAX) * 100));

  return <div className={`kb${canManage ? "" : " is-readonly"}`}>
    {canManage ? <div className="kbTeach">
      <h3><UploadCloud size={16} aria-hidden="true" /> Ensinar a IA</h3>
      <small className="kbLabel">1. Sobre o que é o material?</small>
      <div className="kbChips" role="radiogroup" aria-label="Sobre o que é o material">
        {UPLOAD_KINDS.map((k) => <button key={k} type="button" role="radio" aria-checked={kind === k}
          className={kind === k ? "is-active" : ""} onClick={() => setKind(k)}>{KINDS[k]}</button>)}
      </div>
      <small className="kbLabel">2. Envie o arquivo</small>
      <div className={`kbDrop${drag ? " is-drag" : ""}${busy ? " is-busy" : ""}`} role="button" tabIndex={0}
        onClick={() => !busy && input.current?.click()} onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !busy) { e.preventDefault(); input.current?.click(); } }}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop} aria-label="Enviar documentos">
        {busy && busy !== "texto" && busy !== "edit"
          ? <><span className="kbSpinner" aria-hidden="true" /><b>Lendo “{busy}”…</b><small>A IA está aprendendo. Leva até 1 minuto (PDF lido página a página: até 3).</small></>
          : <><FileText size={26} aria-hidden="true" /><b>Arraste arquivos aqui ou clique para escolher</b>
            <small>PDF, Word, PowerPoint, Excel, CSV ou TXT · até 10 MB · o texto ensina a IA e o original fica na Biblioteca</small></>}
      </div>
      <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => void onFiles(e.target.files)} />
      {pasting ? <div className="kbPaste">
        <textarea rows={4} value={text} maxLength={60000} autoFocus placeholder="Cole aqui um briefing, a transcrição de um áudio, informações de uma campanha…"
          onChange={(e) => setText(e.target.value)} aria-label="Texto para a IA aprender" />
        <div className="kbRow"><button type="button" className="ds-button is-primary" disabled={Boolean(busy) || text.trim().length < 30}
          onClick={() => void run("texto", () => teachFromText(text.trim(), kind)).then((done) => { if (done) { setText(""); setPasting(false); } })}>
          {busy === "texto" ? "Aprendendo…" : "Ensinar"}</button>
          <button type="button" className="ds-button" onClick={() => setPasting(false)}>Cancelar</button></div>
      </div> : <button type="button" className="kbLink" onClick={() => setPasting(true)}><Type size={14} aria-hidden="true" /> ou colar um texto</button>}
      {cloud ? <KnowledgeCloudImport kind={kind} knownNames={data.documents.map((d) => d.name)} onClose={() => setCloud(false)}
        onLearned={(res) => void run(res.document.name, async () => res)} />
        : <button type="button" className="kbLink" onClick={() => setCloud(true)}><FolderDown size={14} aria-hidden="true" /> ou importar do Google Drive ou do Canva</button>}
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      {warn ? <p role="status" className="studioWarn">{warn}</p> : null}
      {ocrFile ? <div className="kbRow">
        <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void readWithOcr()}>
          <ScanText size={14} aria-hidden="true" /> Ler as páginas com IA</button>
        <small className="libHint">Até 20 páginas, leva 1 a 3 minutos.</small>
      </div> : null}
      {ok ? <p className="studioOk">{ok}</p> : null}
      {library ? <p className="libHint" role="status" data-testid="library-learn">{library}</p> : null}
      {data.documents.length ? <div className="kbDocs">
        <h4>Já lidos <span>{data.documents.length}</span></h4>
        <ul>{data.documents.slice(0, 8).map((d) => <li key={d.id || d.name + d.created_at} title={d.summary || undefined}
          className={d.status && d.status !== "aprendido" ? `is-${d.status}` : undefined}>
          {d.kind === "conversa" ? <MessageSquare size={14} aria-hidden="true" /> : <FileText size={14} aria-hidden="true" />}<span>{d.name}</span>
          <small>{KINDS[d.kind] || d.kind} · {d.created_at ? when(d.created_at) : "agora"}
            {d.status === "falhou" ? " · guardado, a IA ainda não aprendeu" : d.status === "pendente" ? " · guardado, aguardando a IA" : ""}</small>
          {d.id && originals[d.id] ? <a className="kbLink" href={originals[d.id]} target="_blank" rel="noreferrer">
            <ExternalLink size={13} aria-hidden="true" /> Abrir original</a> : null}
          {d.status && d.status !== "aprendido" && d.id ? <button type="button" className="kbLink kbRetry" disabled={Boolean(busy)}
            onClick={() => void run(d.name, () => retryKnowledgeDocument(d.id))}><RotateCw size={13} aria-hidden="true" /> Tentar de novo</button> : null}
        </li>)}</ul>
      </div> : null}
    </div> : null}

    <div className="kbKnow">
      <header>
        <h3><Sparkles size={16} aria-hidden="true" /> O que a IA sabe sobre a marca</h3>
        {canManage && editing === null && data.knowledge ? <button type="button" className="kbLink" onClick={() => setEditing(data.knowledge)}><Pencil size={14} aria-hidden="true" /> Corrigir</button> : null}
      </header>
      <div className="kbMeter" title={`${data.knowledge.length} de ${MAX} caracteres`}>
        <span style={{ width: `${used}%` }} /><small>{data.sources} fonte{data.sources === 1 ? "" : "s"} · memória {used}% usada{used >= 90 ? " — a IA vai resumir o menos útil para caber o novo" : ""}</small>
      </div>
      {editing !== null ? <div className="kbPaste">
        <textarea rows={16} value={editing} maxLength={MAX} onChange={(e) => setEditing(e.target.value)} aria-label="Editar conhecimento" />
        <div className="kbRow"><button type="button" className="ds-button is-primary" disabled={busy === "edit"} onClick={() => void saveEdit()}>Salvar</button>
          <button type="button" className="ds-button" onClick={() => setEditing(null)}>Cancelar</button><small>{editing.length}/{MAX}</small></div>
      </div> : sectionsList.length ? <div className="kbCards">{sectionsList.map((s, i) => <article key={`${s.title}-${i}`} className="kbCard">
        <h4>{s.title}</h4><ul>{s.items.map((it, j) => <li key={j}>{it}</li>)}</ul>
      </article>)}</div> : <div className="kbEmpty">
        <Sparkles size={22} aria-hidden="true" />
        <b>A IA ainda não conhece esta marca a fundo</b>
        <p>{canManage ? "Comece pela apresentação da empresa ou pela tabela de produtos. Cada material deixa os posts e as respostas mais certeiros." : "A equipe Mugô vai alimentar com os materiais da marca."}</p>
      </div>}
    </div>
  </div>;
}
