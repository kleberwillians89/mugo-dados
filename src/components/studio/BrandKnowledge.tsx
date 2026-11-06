import { useEffect, useRef, useState, type DragEvent } from "react";
import { FileText, MessageSquare, Pencil, RotateCw, Sparkles, Type, UploadCloud } from "lucide-react";
import { getKnowledge, retryKnowledgeDocument, saveKnowledge, teachFromFile, teachFromText, type BrandKnowledge as Knowledge, type KnowledgeKind, type TeachResult } from "../../app/studio";

const KINDS: Record<KnowledgeKind, string> = { institucional: "Institucional", produto: "Produtos e preços", campanha: "Campanha",
  tom_de_voz: "Tom de voz", restricao: "Restrições", outro: "Outro", conversa: "Conversa" };
const UPLOAD_KINDS = (Object.keys(KINDS) as KnowledgeKind[]).filter((k) => k !== "conversa");
const ACCEPT = ".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md";
const MAX = 6000;
const when = (iso: string) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });

export type KnowledgeSection = { title: string; items: string[] };
/** Quebra o texto da IA em blocos: linha de título ("Produtos:", "# Produtos", "**Produtos**") + marcadores. */
export function parseKnowledge(text: string): KnowledgeSection[] {
  const out: KnowledgeSection[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const bullet = /^([-•*·]|\d+[.)])\s+/.test(line);
    const heading = !bullet && (/^#{1,4}\s/.test(line) || /^\*\*[^*]+\*\*:?$/.test(line) || (/:$/.test(line) && line.length <= 60));
    if (heading) { out.push({ title: line.replace(/^#+\s*|\*\*|:$/g, "").replace(/:$/, "").trim(), items: [] }); continue; }
    if (!out.length) out.push({ title: "Sobre a marca", items: [] });
    out[out.length - 1].items.push(line.replace(/^([-•*·]|\d+[.)])\s+/, "").replace(/\*\*/g, ""));
  }
  return out.filter((s) => s.items.length);
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
  const [busy, setBusy] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [warn, setWarn] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { getKnowledge().then(setData).catch(() => setData({ knowledge: "", sources: 0, updated_at: null, documents: [] })); }, [version]);

  async function run(label: string, task: () => Promise<TeachResult>) {
    setBusy(label); setError(null); setOk(null); setWarn(null);
    try {
      const res = await task();
      setData((d) => ({ knowledge: res.knowledge, sources: res.sources, updated_at: new Date().toISOString(),
        documents: [res.document, ...(d?.documents || []).filter((x) => x.id !== res.document.id)] }));
      if (res.warning) setWarn(`“${res.document.name}”: ${res.warning}`);
      else setOk(res.document.summary ? `Aprendi com “${res.document.name}”: ${res.document.summary}` : `Aprendi com “${res.document.name}”.`);
      return true;
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível processar."); return false; }
    finally { setBusy(null); }
  }
  async function onFiles(files: FileList | File[] | null) {
    for (const file of Array.from(files || [])) await run(file.name, () => teachFromFile(file, kind));
    if (input.current) input.current.value = "";
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
          ? <><span className="kbSpinner" aria-hidden="true" /><b>Lendo “{busy}”…</b><small>A IA está aprendendo. Leva até 1 minuto.</small></>
          : <><FileText size={26} aria-hidden="true" /><b>Arraste arquivos aqui ou clique para escolher</b>
            <small>PDF, Word, PowerPoint, Excel, CSV ou TXT · até 10 MB · o conteúdo fica guardado para a IA consultar</small></>}
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
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      {warn ? <p role="status" className="studioWarn">{warn}</p> : null}
      {ok ? <p className="studioOk">{ok}</p> : null}
      {data.documents.length ? <div className="kbDocs">
        <h4>Já lidos <span>{data.documents.length}</span></h4>
        <ul>{data.documents.slice(0, 8).map((d) => <li key={d.id || d.name + d.created_at} title={d.summary || undefined}
          className={d.status && d.status !== "aprendido" ? `is-${d.status}` : undefined}>
          {d.kind === "conversa" ? <MessageSquare size={14} aria-hidden="true" /> : <FileText size={14} aria-hidden="true" />}<span>{d.name}</span>
          <small>{KINDS[d.kind] || d.kind} · {d.created_at ? when(d.created_at) : "agora"}
            {d.status === "falhou" ? " · guardado, a IA ainda não aprendeu" : d.status === "pendente" ? " · guardado, aguardando a IA" : ""}</small>
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
