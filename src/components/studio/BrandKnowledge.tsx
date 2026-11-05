import { useEffect, useRef, useState } from "react";
import { getKnowledge, saveKnowledge, teachFromFile, teachFromText, type BrandKnowledge as Knowledge, type KnowledgeKind } from "../../app/studio";

const KINDS: Record<KnowledgeKind, string> = { institucional: "Institucional", produto: "Produtos e preços", campanha: "Campanha",
  tom_de_voz: "Tom de voz", restricao: "Restrições", outro: "Outro" };
const ACCEPT = ".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md";
const when = (iso: string) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });

/**
 * Conhecimento da marca: envie documentos (ou cole texto) e a IA aprende com eles.
 * O arquivo não fica guardado — só o que a IA aprendeu, consolidado num texto de tamanho fixo.
 */
export default function BrandKnowledge({ canManage }: { canManage: boolean }) {
  const [data, setData] = useState<Knowledge | null>(null);
  const [kind, setKind] = useState<KnowledgeKind>("institucional");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { getKnowledge().then(setData).catch(() => setData({ knowledge: "", sources: 0, updated_at: null, documents: [] })); }, []);

  async function run(label: string, task: () => Promise<{ document: Knowledge["documents"][number]; knowledge: string; sources: number }>) {
    setBusy(label); setError(null); setOk(null);
    try {
      const res = await task();
      setData((d) => ({ knowledge: res.knowledge, sources: res.sources, updated_at: new Date().toISOString(), documents: [res.document, ...(d?.documents || [])] }));
      setOk(`A IA aprendeu com “${res.document.name}”${res.document.summary ? `: ${res.document.summary}` : "."}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível processar."); }
    finally { setBusy(null); }
  }

  async function onFiles(files: FileList | null) {
    for (const file of Array.from(files || [])) await run(file.name, () => teachFromFile(file, kind));
    if (input.current) input.current.value = "";
  }

  async function saveEdit() {
    if (editing === null) return;
    setBusy("edit"); setError(null);
    try { const res = await saveKnowledge(editing); setData((d) => d && { ...d, knowledge: res.knowledge }); setEditing(null); setOk("Conhecimento atualizado."); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar."); }
    finally { setBusy(null); }
  }

  if (!data) return <p className="libHint">Carregando…</p>;
  return <div className="knowledge">
    {canManage ? <div className="knowledgeInput">
      <p className="libHint">Envie apresentações, manual de marca, tabela de produtos, briefings… A IA lê, guarda o que importa e <b>o arquivo é descartado</b>. Quanto mais material, mais ela sabe sobre a marca.</p>
      <div className="knowledgeRow">
        <select value={kind} onChange={(e) => setKind(e.target.value as KnowledgeKind)} aria-label="Tipo do material">
          {(Object.keys(KINDS) as KnowledgeKind[]).map((k) => <option key={k} value={k}>{KINDS[k]}</option>)}
        </select>
        <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => void onFiles(e.target.files)} />
        <button type="button" className="ds-button ds-button--primary" disabled={Boolean(busy)} onClick={() => input.current?.click()}>
          {busy && busy !== "texto" && busy !== "edit" ? `Lendo ${busy}…` : "Enviar documentos"}
        </button>
        <small>PDF, DOCX, PPTX, XLSX, CSV, TXT · até 10 MB cada</small>
      </div>
      <textarea rows={3} value={text} maxLength={60000} placeholder="Ou cole aqui um texto (briefing, informações da campanha, respostas do cliente)…"
        onChange={(e) => setText(e.target.value)} aria-label="Texto para a IA aprender" />
      <div className="knowledgeRow"><button type="button" className="ds-button" disabled={Boolean(busy) || text.trim().length < 30}
        onClick={() => void run("texto", () => teachFromText(text.trim(), kind)).then(() => setText(""))}>{busy === "texto" ? "Aprendendo…" : "Ensinar este texto"}</button></div>
    </div> : null}
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {ok ? <p className="studioOk">{ok}</p> : null}

    <section className="knowledgeBox" aria-label="O que a IA sabe sobre a marca">
      <header><b>O que a IA sabe sobre a marca</b><span>{data.sources} fonte{data.sources === 1 ? "" : "s"}{data.updated_at ? ` · atualizado em ${when(data.updated_at)}` : ""}</span>
        {canManage && editing === null && data.knowledge ? <button type="button" className="ds-button" onClick={() => setEditing(data.knowledge)}>Corrigir</button> : null}
      </header>
      {editing !== null ? <>
        <textarea rows={14} value={editing} maxLength={6000} onChange={(e) => setEditing(e.target.value)} aria-label="Editar conhecimento" />
        <div className="knowledgeRow"><button type="button" className="ds-button ds-button--primary" disabled={busy === "edit"} onClick={() => void saveEdit()}>Salvar</button>
          <button type="button" className="ds-button" onClick={() => setEditing(null)}>Cancelar</button><small>{editing.length}/6000</small></div>
      </> : data.knowledge ? <pre className="knowledgeText">{data.knowledge}</pre>
        : <p className="chatEmpty">Ainda vazio. {canManage ? "Envie o primeiro documento acima." : "A equipe Mugô vai alimentar com os materiais da marca."}</p>}
    </section>

    {data.documents.length ? <section aria-label="Materiais já lidos">
      <h3 className="crmGroupTitle">Materiais já lidos <span>{data.documents.length}</span></h3>
      <ul className="knowledgeDocs">{data.documents.map((d) => <li key={d.id || d.name + d.created_at}>
        <div><b>{d.name}</b> <small>{KINDS[d.kind] || d.kind} · {d.created_at ? when(d.created_at) : "agora"}{d.truncated ? " · lido só o começo (documento longo)" : ""}</small></div>
        {d.summary ? <p>{d.summary}</p> : null}
      </li>)}</ul>
    </section> : null}
  </div>;
}
