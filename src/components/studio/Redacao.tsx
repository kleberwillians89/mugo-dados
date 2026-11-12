import { AlignCenter, AlignJustify, AlignLeft, AlignRight, List, ListOrdered, Quote, Redo2, RemoveFormatting, TriangleAlert, Undo2 } from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { EditorContent, useEditor, useEditorState, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import TextAlign from "@tiptap/extension-text-align";
import { CharacterCount, Placeholder } from "@tiptap/extensions";
import Drawer from "../Drawer";
import { STUDIO_FORMATS, type StudioFormat } from "../../app/studio";
import { getActiveClientId } from "../../app/activeClient";
import {
  DOC_KIND_LABEL, PLATFORM_FORMATS, PLATFORM_LABEL, PLATFORM_ORDER, createDocument, documentAI, documentToCalendar, getDocument,
  listDocuments, saveDocument, type DocAIAction, type DocAIResult, type DocKind, type DocSummary, type Platform, type StudioDocument,
} from "../../app/contentOps";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const SAVE_DELAY_MS = 1200;

/** Texto da IA (parágrafos separados por linha em branco) vira HTML seguro para o editor. */
function textToHtml(text: string): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return text.split(/\n{2,}/).map((block) => `<p>${esc(block.trim()).replace(/\n/g, "<br>")}</p>`).join("");
}

function when(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

type Props = { canManage: boolean; onOpenCalendar?: () => void };

/**
 * Redação (trazida da iAgência): editor de texto estilo Word por marca, com a IA da marca para
 * escrever, continuar, reescrever, encurtar, expandir e corrigir. O texto pode virar post no Calendário.
 */
export default function Redacao({ canManage, onOpenCalendar }: Props) {
  const clientId = getActiveClientId();
  const [list, setList] = useState<DocSummary[]>([]);
  const [doc, setDoc] = useState<StudioDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await listDocuments();
      if (getActiveClientId() !== clientId) return;
      setList(data.documents || []);
    } catch (cause) { setError(message(cause, "Não foi possível carregar os documentos.")); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  async function open(id: string) {
    setBusy(`open:${id}`); setError(null); setNotice(null);
    try { setDoc((await getDocument(id)).document); }
    catch (cause) { setError(message(cause, "Não foi possível abrir o documento.")); }
    finally { setBusy(null); }
  }

  async function create() {
    setBusy("create"); setError(null); setNotice(null);
    try {
      const created = (await createDocument({ title: "Sem título", kind: "livre" })).document;
      setList((l) => [created, ...l]); setDoc(created);
    } catch (cause) { setError(message(cause, "Não foi possível criar o documento.")); }
    finally { setBusy(null); }
  }

  const onSaved = useCallback((saved: StudioDocument) => {
    setList((l) => [{ ...saved, excerpt: saved.content_text.slice(0, 160) }, ...l.filter((x) => x.id !== saved.id)]);
  }, []);

  const shown = list.filter((d) => !query.trim() || `${d.title} ${d.excerpt || ""}`.toLowerCase().includes(query.trim().toLowerCase()));

  return <section className="redacao" aria-label="Redação">
    <aside className="redacaoList" aria-label="Documentos">
      {canManage ? <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void create()}>
        {busy === "create" ? "Criando…" : "+ Novo documento"}</button> : null}
      <input type="search" placeholder="Buscar nos textos" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Buscar documentos" />
      {loading ? <p className="libHint">Carregando…</p> : null}
      {!loading && !list.length ? <p className="libHint">Nenhum documento ainda.{canManage ? " Clique em + Novo documento." : ""}</p> : null}
      <ul>{shown.map((d) => <li key={d.id}>
        <button type="button" className={doc?.id === d.id ? "is-active" : ""} disabled={Boolean(busy)} onClick={() => void open(d.id)}>
          <b>{d.title || "Sem título"}</b>
          <small>{DOC_KIND_LABEL[d.kind]} · {when(d.updated_at)}{d.calendar_item_id ? " · no Calendário" : ""}</small>
          {d.excerpt ? <span>{d.excerpt}</span> : null}
        </button>
      </li>)}</ul>
    </aside>
    <div className="redacaoMain">
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      {notice ? <p className="studioOk">{notice}{onOpenCalendar ? <> <button type="button" className="studioLink" onClick={onOpenCalendar}>Abrir o Calendário</button></> : null}</p> : null}
      {doc ? <DocumentEditor key={doc.id} doc={doc} canManage={canManage} onSaved={onSaved} onNotice={setNotice}
        onArchived={(id) => { setDoc(null); setList((l) => l.filter((x) => x.id !== id)); }} />
        : <div className="redacaoEmpty"><p>Abra um documento ao lado{canManage ? " ou crie um novo" : ""}.</p>
          <p className="libHint">A Redação é o editor de texto da marca: escreva posts, legendas, roteiros, artigos, e-mails e releases com a IA da marca. O texto pronto vira post no Calendário.</p></div>}
    </div>
  </section>;
}

type SaveState = "salvo" | "pendente" | "salvando" | "erro";

function DocumentEditor({ doc, canManage, onSaved, onNotice, onArchived }: {
  doc: StudioDocument; canManage: boolean; onSaved: (d: StudioDocument) => void; onNotice: (n: string | null) => void; onArchived: (id: string) => void;
}) {
  const [title, setTitle] = useState(doc.title);
  const [kind, setKind] = useState<DocKind>(doc.kind);
  const [saveState, setSaveState] = useState<SaveState>("salvo");
  const [savedAt, setSavedAt] = useState(doc.updated_at);
  const [aiOpen, setAiOpen] = useState(true);
  const [toCalendar, setToCalendar] = useState(false);
  const [linked, setLinked] = useState(doc.calendar_item_id);
  const pending = useRef<{ title?: string; kind?: DocKind; content_html?: string }>({});
  const timer = useRef<number | null>(null);

  const flush = useCallback(async () => {
    if (timer.current) { window.clearTimeout(timer.current); timer.current = null; }
    const patch = pending.current;
    if (!Object.keys(patch).length) return;
    pending.current = {};
    setSaveState("salvando");
    try {
      const saved = (await saveDocument(doc.id, patch)).document;
      setSavedAt(saved.updated_at);
      setSaveState(Object.keys(pending.current).length ? "pendente" : "salvo");
      onSaved(saved);
    } catch {
      pending.current = { ...patch, ...pending.current };
      setSaveState("erro");
    }
  }, [doc.id, onSaved]);

  const queue = useCallback((patch: { title?: string; kind?: DocKind; content_html?: string }) => {
    if (!canManage) return;
    pending.current = { ...pending.current, ...patch };
    setSaveState("pendente");
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(), SAVE_DELAY_MS);
  }, [canManage, flush]);

  // Ao trocar de documento ou sair da tela, salva o que ficou pendente.
  useEffect(() => () => { void flush(); }, [flush]);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ link: { openOnClick: false, autolink: true } }),
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      Placeholder.configure({ placeholder: "Comece a escrever, ou peça para a IA da marca escrever ao lado…" }),
      CharacterCount,
    ],
    content: doc.content_html || "",
    editable: canManage,
    onUpdate: ({ editor: ed }) => queue({ content_html: ed.getHTML() }),
  });

  const counts = useEditorState({ editor, selector: ({ editor: ed }) => ({
    words: ed?.storage.characterCount?.words() ?? 0, chars: ed?.storage.characterCount?.characters() ?? 0,
  }) });

  async function archive() {
    if (!window.confirm("Arquivar este documento? Ele some da lista (o que já foi para o Calendário continua lá).")) return;
    await flush();
    try { await saveDocument(doc.id, { status: "arquivado" }); onArchived(doc.id); }
    catch (cause) { onNotice(message(cause, "Não foi possível arquivar.")); }
  }

  function downloadWord() {
    if (!editor) return;
    const html = `<html><head><meta charset="utf-8"><title>${title.replace(/</g, "")}</title></head><body><h1>${title.replace(/</g, "&lt;")}</h1>${editor.getHTML()}</body></html>`;
    const url = URL.createObjectURL(new Blob(["﻿", html], { type: "application/msword" }));
    const a = document.createElement("a");
    a.href = url; a.download = `${(title || "documento").replace(/[\\/:*?"<>|]+/g, "-").slice(0, 80)}.doc`;
    a.click(); URL.revokeObjectURL(url);
  }

  async function copyText() {
    if (!editor) return;
    try { await navigator.clipboard.writeText(editor.getText({ blockSeparator: "\n\n" })); onNotice("Texto copiado."); } catch { /* segue na tela */ }
  }

  const status = { salvo: `Salvo ${when(savedAt)}`, pendente: "Alterações não salvas…", salvando: "Salvando…", erro: "Não salvou. Tentando de novo ao editar." }[saveState];

  return <div className="redacaoDoc">
    <div className="redacaoHead">
      <input className="redacaoTitle" aria-label="Título do documento" value={title} maxLength={200} disabled={!canManage} placeholder="Sem título"
        onChange={(e) => { setTitle(e.target.value); queue({ title: e.target.value }); }} onBlur={() => void flush()} />
      <div className="redacaoMeta">
        <label>Tipo<select value={kind} disabled={!canManage} onChange={(e) => { const k = e.target.value as DocKind; setKind(k); queue({ kind: k }); }}>
          {(Object.keys(DOC_KIND_LABEL) as DocKind[]).map((k) => <option key={k} value={k}>{DOC_KIND_LABEL[k]}</option>)}</select></label>
        <span className={`redacaoSave is-${saveState}`} aria-live="polite">{status}</span>
        <span className="redacaoCount">{counts?.words ?? 0} palavras · {counts?.chars ?? 0} caracteres</span>
        <button type="button" className="studioLink" onClick={() => void copyText()}>Copiar texto</button>
        <button type="button" className="studioLink" onClick={downloadWord}>Baixar (Word)</button>
        {canManage ? <button type="button" className="ds-button" onClick={() => { void flush(); setToCalendar(true); }}>Enviar ao Calendário</button> : null}
        {canManage ? <button type="button" className="studioLink" onClick={() => setAiOpen((v) => !v)}>{aiOpen ? "Esconder IA" : "IA da marca"}</button> : null}
        {canManage ? <button type="button" className="studioLink is-danger" onClick={() => void archive()}>Arquivar</button> : null}
      </div>
    </div>
    {canManage && editor ? <Toolbar editor={editor} /> : null}
    <div className={`redacaoBody${aiOpen && canManage ? " has-ai" : ""}`}>
      <div className="redacaoPaper" onClick={() => editor?.chain().focus().run()}>
        <EditorContent editor={editor} className="redacaoEditor" />
      </div>
      {aiOpen && canManage && editor ? <AIPanel editor={editor} kind={kind} title={title} onTitle={(t) => { setTitle(t); queue({ title: t }); }} /> : null}
    </div>
    <CalendarDrawer open={toCalendar} doc={{ ...doc, calendar_item_id: linked }} onClose={() => setToCalendar(false)}
      onDone={(text, id) => { setToCalendar(false); setLinked(id); onNotice(text); }} />
  </div>;
}

function Toolbar({ editor }: { editor: Editor }) {
  const s = useEditorState({ editor, selector: ({ editor: ed }) => ({
    bold: ed.isActive("bold"), italic: ed.isActive("italic"), underline: ed.isActive("underline"), strike: ed.isActive("strike"),
    h1: ed.isActive("heading", { level: 1 }), h2: ed.isActive("heading", { level: 2 }), h3: ed.isActive("heading", { level: 3 }),
    bullet: ed.isActive("bulletList"), ordered: ed.isActive("orderedList"), quote: ed.isActive("blockquote"),
    left: ed.isActive({ textAlign: "left" }), center: ed.isActive({ textAlign: "center" }), right: ed.isActive({ textAlign: "right" }), justify: ed.isActive({ textAlign: "justify" }),
    undo: ed.can().undo(), redo: ed.can().redo(),
  }) });
  const block = s.h1 ? "h1" : s.h2 ? "h2" : s.h3 ? "h3" : "p";
  const btn = (label: ReactNode, title: string, active: boolean, run: () => void, disabled = false) =>
    <button type="button" title={title} aria-label={title} aria-pressed={active} className={active ? "is-active" : ""} disabled={disabled}
      onMouseDown={(e) => e.preventDefault()} onClick={run}>{label}</button>;
  const c = () => editor.chain().focus();
  return <div className="redacaoToolbar" role="toolbar" aria-label="Formatação">
    {btn(<Undo2 className="uiGlyph" size={15} aria-hidden="true" />, "Desfazer", false, () => c().undo().run(), !s.undo)}
    {btn(<Redo2 className="uiGlyph" size={15} aria-hidden="true" />, "Refazer", false, () => c().redo().run(), !s.redo)}
    <span className="sep" />
    <select aria-label="Estilo do parágrafo" value={block} onChange={(e) => {
      const v = e.target.value;
      if (v === "p") c().setParagraph().run(); else c().setHeading({ level: Number(v.slice(1)) as 1 | 2 | 3 }).run();
    }}><option value="p">Texto normal</option><option value="h1">Título 1</option><option value="h2">Título 2</option><option value="h3">Título 3</option></select>
    <span className="sep" />
    {btn("B", "Negrito (Ctrl+B)", s.bold, () => c().toggleBold().run())}
    {btn("I", "Itálico (Ctrl+I)", s.italic, () => c().toggleItalic().run())}
    {btn("U", "Sublinhado (Ctrl+U)", s.underline, () => c().toggleUnderline().run())}
    {btn("S", "Tachado", s.strike, () => c().toggleStrike().run())}
    <span className="sep" />
    {btn(<List className="uiGlyph" size={15} aria-hidden="true" />, "Lista", s.bullet, () => c().toggleBulletList().run())}
    {btn(<ListOrdered className="uiGlyph" size={15} aria-hidden="true" />, "Lista numerada", s.ordered, () => c().toggleOrderedList().run())}
    {btn(<Quote className="uiGlyph" size={15} aria-hidden="true" />, "Citação", s.quote, () => c().toggleBlockquote().run())}
    <span className="sep" />
    {btn(<AlignLeft className="uiGlyph" size={15} aria-hidden="true" />, "Alinhar à esquerda", s.left, () => c().setTextAlign("left").run())}
    {btn(<AlignCenter className="uiGlyph" size={15} aria-hidden="true" />, "Centralizar", s.center, () => c().setTextAlign("center").run())}
    {btn(<AlignRight className="uiGlyph" size={15} aria-hidden="true" />, "Alinhar à direita", s.right, () => c().setTextAlign("right").run())}
    {btn(<AlignJustify className="uiGlyph" size={15} aria-hidden="true" />, "Justificar", s.justify, () => c().setTextAlign("justify").run())}
    <span className="sep" />
    {btn(<RemoveFormatting className="uiGlyph" size={15} aria-hidden="true" />, "Limpar formatação", false, () => c().unsetAllMarks().clearNodes().run())}
  </div>;
}

const SELECTION_ACTIONS: { action: DocAIAction; label: string }[] = [
  { action: "reescrever", label: "Reescrever" }, { action: "encurtar", label: "Encurtar" },
  { action: "expandir", label: "Expandir" }, { action: "corrigir", label: "Corrigir" },
];

function AIPanel({ editor, kind, title, onTitle }: { editor: Editor; kind: DocKind; title: string; onTitle: (t: string) => void }) {
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState<DocAIAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<(DocAIResult & { range: { from: number; to: number } | null }) | null>(null);
  const selection = useEditorState({ editor, selector: ({ editor: ed }) => {
    const { from, to } = ed.state.selection;
    return from === to ? "" : ed.state.doc.textBetween(from, to, "\n\n");
  } });
  const hasText = useEditorState({ editor, selector: ({ editor: ed }) => !ed.isEmpty });

  async function ask(action: DocAIAction) {
    setBusy(action); setError(null); setResult(null);
    const { from, to } = editor.state.selection;
    try {
      const out = await documentAI({ action, kind, title, instruction, selection, document_text: editor.getText({ blockSeparator: "\n\n" }) });
      setResult({ ...out, range: from === to ? null : { from, to } });
    } catch (cause) { setError(message(cause, "A IA não respondeu agora. Tente de novo.")); }
    finally { setBusy(null); }
  }

  function apply(mode: "inserir" | "substituir") {
    if (!result?.text) return;
    const html = textToHtml(result.text);
    if (mode === "substituir" && result.range) editor.chain().focus().insertContentAt(result.range, html).run();
    else if (result.action === "continuar" || !editor.state.selection.empty) editor.chain().focus("end").insertContent(html).run();
    else editor.chain().focus().insertContent(html).run();
    setResult(null);
  }

  const canReplace = Boolean(result?.range) && ["reescrever", "encurtar", "expandir", "corrigir"].includes(result?.action || "");

  return <aside className="redacaoAI" aria-label="IA da marca">
    <h3>IA da marca</h3>
    <p className="libHint">Escreve no tom de voz da marca, com o que o cliente aprovou e o que performou. Não inventa oferta nem número.</p>
    <label>O que você quer?<textarea rows={4} maxLength={1500} value={instruction} onChange={(e) => setInstruction(e.target.value)}
      placeholder="Ex.: legenda para o lançamento do kit Oud, tom elegante, CTA para o link da bio" /></label>
    <div className="redacaoAIActions">
      <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || (!instruction.trim() && !title.trim())} onClick={() => void ask("escrever")}>
        {busy === "escrever" ? "Escrevendo…" : "Escrever"}</button>
      <button type="button" className="ds-button" disabled={Boolean(busy) || !hasText} onClick={() => void ask("continuar")}>{busy === "continuar" ? "Escrevendo…" : "Continuar o texto"}</button>
      <button type="button" className="ds-button" disabled={Boolean(busy) || !hasText} onClick={() => void ask("titulos")}>{busy === "titulos" ? "Pensando…" : "Sugerir títulos"}</button>
    </div>
    <p className="redacaoAISel">{selection ? <>Trecho selecionado: <b>{selection.length} caracteres</b></> : "Selecione um trecho no texto para reescrever, encurtar, expandir ou corrigir."}</p>
    <div className="redacaoAIActions">
      {SELECTION_ACTIONS.map((a) => <button key={a.action} type="button" className="ds-button" disabled={Boolean(busy) || !selection} onClick={() => void ask(a.action)}>
        {busy === a.action ? "…" : a.label}</button>)}
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {result?.titles?.length ? <div className="redacaoAIResult"><b>Títulos sugeridos</b>
      <ul>{result.titles.map((t) => <li key={t}><button type="button" className="studioLink" onClick={() => { onTitle(t); setResult(null); }}>{t}</button></li>)}</ul></div> : null}
    {result?.text ? <div className="redacaoAIResult">
      <b>Sugestão da IA</b>
      <div className="redacaoAIText">{result.text.split(/\n{2,}/).map((p, i) => <p key={i}>{p}</p>)}</div>
      {result.flags.length ? <p className="clipWarn">Palavra a evitar: {result.flags.join(", ")}</p> : null}
      {result.guard.map((g) => <p key={`${g.type}:${g.text}`} className="clipWarn"><TriangleAlert className="uiGlyph" size={14} aria-hidden="true" /> {g.fix}</p>)}
      <div className="redacaoAIActions">
        {canReplace ? <button type="button" className="ds-button is-primary" onClick={() => apply("substituir")}>Substituir o trecho</button> : null}
        <button type="button" className={`ds-button${canReplace ? "" : " is-primary"}`} onClick={() => apply("inserir")}>{result.action === "continuar" ? "Inserir no fim" : "Inserir no texto"}</button>
        <button type="button" className="studioLink" onClick={() => setResult(null)}>Descartar</button>
      </div>
    </div> : null}
  </aside>;
}

function CalendarDrawer({ open, doc, onClose, onDone }: { open: boolean; doc: StudioDocument; onClose: () => void; onDone: (text: string, calendarItemId: string) => void }) {
  const tomorrow = useMemo(() => { const d = new Date(); d.setDate(d.getDate() + 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }, []);
  const [date, setDate] = useState(tomorrow);
  const [time, setTime] = useState("19:00");
  const [channel, setChannel] = useState<Platform>("instagram");
  const [format, setFormat] = useState<StudioFormat>("imagem");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const already = Boolean(doc.calendar_item_id);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await documentToCalendar(doc.id, { scheduled_at: `${date}T${time}:00-03:00`, channel, format });
      onDone(r.created ? "Post criado no Calendário como rascunho. Abra por lá para anexar a arte e mandar para aprovação."
        : r.updated ? "O post deste texto no Calendário foi atualizado com a versão nova." : "Este texto já virou post e o post já foi aprovado: edite por lá.", r.calendar_item_id);
    } catch (cause) { setError(message(cause, "Não foi possível enviar ao Calendário.")); }
    finally { setBusy(false); }
  }

  return <Drawer open={open} title="Enviar ao Calendário" description={already ? "Este texto já tem um post no Calendário: enviar de novo atualiza o mesmo post (não cria outro)." : "O texto vira a legenda de um post em rascunho, que segue a aprovação de sempre."}
    onClose={() => { if (!busy) onClose(); }}>
    <form className="studioForm" onSubmit={submit}>
      {!already ? <>
        <div className="studioRow">
          <label>Data<input type="date" required value={date} onChange={(e) => setDate(e.target.value)} /></label>
          <label>Horário<input type="time" required value={time} onChange={(e) => setTime(e.target.value)} /></label>
        </div>
        <div className="studioRow">
          <label>Plataforma<select value={channel} onChange={(e) => { const p = e.target.value as Platform; setChannel(p); if (!PLATFORM_FORMATS[p].includes(format)) setFormat(PLATFORM_FORMATS[p][0]); }}>
            {PLATFORM_ORDER.map((p) => <option key={p} value={p}>{PLATFORM_LABEL[p]}</option>)}</select></label>
          <label>Formato<select value={format} onChange={(e) => setFormat(e.target.value as StudioFormat)}>
            {PLATFORM_FORMATS[channel].map((f) => <option key={f} value={f}>{STUDIO_FORMATS[f]}</option>)}</select></label>
        </div>
      </> : null}
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      <div className="studioActions"><button type="button" className="ds-button" disabled={busy} onClick={onClose}>Cancelar</button>
        <button className="ds-button is-primary" disabled={busy}>{busy ? "Enviando…" : already ? "Atualizar o post" : "Criar post"}</button></div>
    </form>
  </Drawer>;
}
