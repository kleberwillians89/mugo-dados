import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, FileSearch, FileText, Plus, Trash2, UploadCloud } from "lucide-react";
import { applyBrandImport, previewBrandImport, type ApprovedField, type ImportCompetitor, type ImportField, type ImportPillar, type ImportPreview, type ImportValue } from "../../app/brandImport";
import { BRAND_PROFILE_SAVED, STUDIO_CHANNELS, STUDIO_FORMATS, getKnowledge, teachFromFile, type BrandDocument, type StudioChannel } from "../../app/studio";
import { clearDashboardCacheByPrefix } from "../../hooks/dashboard/cache";
import { getActiveClientId } from "../../app/activeClient";
import { GROUP_LABELS, STATUS_LABELS, buildApproved, competitorSummary, describeValue, fieldProblem, listToText, pillarTotal, suggestedKeys, textToList } from "./brandImport.helpers";

const ACCEPT = ".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md";
type Mode = ApprovedField["mode"];

/**
 * Contexto da Marca → Importar configurações do planejamento.
 * 1) escolhe (ou envia) um documento já guardado; 2) a IA lê o texto guardado UMA vez e monta a prévia;
 * 3) a pessoa revisa, corrige e marca; 4) só depois de confirmar, grava os campos marcados. Nada é marcado sozinho
 * em regra operacional (pilares, frequência, formatos, plataformas).
 */
export default function BrandImport({ onApplied }: { onApplied?: () => void }) {
  const [docs, setDocs] = useState<BrandDocument[] | null>(null);
  const [docId, setDocId] = useState("");
  const [busy, setBusy] = useState<"upload" | "preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, ImportValue>>({});
  const [modes, setModes] = useState<Record<string, Mode>>({});
  const [confirming, setConfirming] = useState(false);
  const [applied, setApplied] = useState<{ labels: string[]; competitors: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getKnowledge().then((k) => {
      const list = k.documents.filter((d) => d.kind !== "conversa" && d.id);
      setDocs(list);
      setDocId((cur) => cur || list[0]?.id || "");
    }).catch(() => setDocs([]));
  }, []);

  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy("upload"); setError(null);
    try {
      const res = await teachFromFile(file, "institucional");
      setDocs((list) => [res.document, ...(list || []).filter((d) => d.id !== res.document.id)]);
      setDocId(res.document.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível ler o arquivo."); }
    finally { setBusy(null); if (input.current) input.current.value = ""; }
  }

  async function read() {
    if (!docId) return;
    setBusy("preview"); setError(null); setApplied(null); setConfirming(false);
    try {
      const res = await previewBrandImport(docId);
      setPreview(res); setSelected(new Set()); setModes({});
      setDrafts(Object.fromEntries(res.fields.map((f) => [f.key, f.value])));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível ler o documento."); }
    finally { setBusy(null); }
  }

  const fields = useMemo(() => preview?.fields.filter((f) => f.status !== "missing") || [], [preview]);
  const problems = useMemo(() => {
    // Plataformas que valerão depois de aplicar: as aprovadas agora ou as atuais.
    const current = (preview?.fields.find((f) => f.key === "editorial_platforms")?.current as string[] | null) || [];
    const platforms = selected.has("editorial_platforms") ? ((drafts.editorial_platforms as string[] | null) || []) : current;
    return Object.fromEntries(fields.filter((f) => selected.has(f.key))
      .map((f) => [f.key, fieldProblem(f, drafts[f.key], platforms)]).filter(([, p]) => p)) as Record<string, string>;
  }, [preview, fields, selected, drafts]);
  const blocked = Object.keys(problems).length > 0;

  function toggle(key: string) {
    setConfirming(false);
    setSelected((cur) => { const next = new Set(cur); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  }
  function setDraft(key: string, value: ImportValue) { setConfirming(false); setDrafts((d) => ({ ...d, [key]: value })); }

  async function confirmApply() {
    if (!preview || blocked || !selected.size) return;
    const clientId = getActiveClientId();
    setBusy("apply"); setError(null);
    try {
      const res = await applyBrandImport(preview.document.id, buildApproved(preview.fields, selected, drafts, modes));
      if (res.profile) window.dispatchEvent(new CustomEvent(BRAND_PROFILE_SAVED, { detail: res.profile }));
      if (res.business_context) {
        clearDashboardCacheByPrefix(`intelligence-workspace|c=${clientId}:`);
        clearDashboardCacheByPrefix(`intelligence-history|c=${clientId}|`);
      }
      setApplied({ labels: res.applied, competitors: res.competitors ? competitorSummary(res.competitors) : "" }); setPreview(null); setSelected(new Set()); setConfirming(false);
      onApplied?.();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível aplicar."); }
    finally { setBusy(null); }
  }

  const groups = (Object.keys(GROUP_LABELS) as (keyof typeof GROUP_LABELS)[]).map((g) => ({ id: g, items: fields.filter((f) => f.group === g) })).filter((g) => g.items.length);

  return <section className="bcCard bcImport" aria-labelledby="bc-import-title" data-testid="brand-import">
    <header className="bcCardHead"><div>
      <h2 id="bc-import-title"><FileSearch size={18} aria-hidden="true" /> Importar configurações do planejamento</h2>
      <p className="libHint">A IA lê o planejamento ou brand book e mostra o que encontrou, campo a campo, com o trecho de origem.
        Nada muda até você revisar, marcar os campos e confirmar.</p>
    </div></header>

    <div className="bcImportPick">
      {docs === null ? <p className="libHint" role="status">Carregando documentos…</p> : docs.length ? <label>
        <span className="kbLabel">Documento</span>
        <select value={docId} onChange={(e) => { setDocId(e.target.value); setPreview(null); }} disabled={Boolean(busy)} aria-label="Documento para importar">
          {docs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </label> : <p className="libHint">Nenhum documento enviado ainda. Envie o planejamento ou o brand book.</p>}
      <div className="kbRow">
        <button type="button" className="ds-button is-primary" disabled={!docId || Boolean(busy)} onClick={() => void read()}>
          {busy === "preview" ? "Lendo o documento… (até 2 min)" : "Ler e montar prévia"}</button>
        <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => input.current?.click()}>
          <UploadCloud size={14} aria-hidden="true" /> {busy === "upload" ? "Enviando…" : "Enviar outro documento"}</button>
        <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => void upload(e.target.files?.[0])} aria-label="Arquivo do planejamento" />
      </div>
      <small className="libHint">PDF com texto selecionável, Word, PowerPoint, Excel, CSV ou TXT. PDF escaneado (só imagem) não é lido: envie a versão com texto. O arquivo original não fica guardado, só o texto.</small>
    </div>

    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {applied ? <p role="status" className="studioOk"><CheckCircle2 size={14} aria-hidden="true" /> Aplicado: {applied.labels.join(", ")}. Os demais campos ficaram como estavam.
      A IA já usa o que foi aplicado nas pautas, legendas, respostas e análises.{applied.competitors ? ` ${applied.competitors}` : ""}</p> : null}

    {preview ? <div className="bcImportReview">
      <p className="bcImportSummary" role="status"><FileText size={14} aria-hidden="true" /> <b>{preview.document.name}</b>: {preview.counts.found} encontrado(s),
        {" "}{preview.counts.ambiguous} para revisar, {preview.counts.missing} não encontrado(s).</p>
      {preview.document.parts > 1 ? <p className="libHint">Documento longo: lido inteiro, em {preview.document.parts} partes ({preview.document.read_chars.toLocaleString("pt-BR")} caracteres).</p> : null}
      {preview.document.partial ? <p className="studioWarn">O documento passa de 200 mil caracteres: a IA leu os primeiros {preview.document.read_chars.toLocaleString("pt-BR")}. Para o restante, envie a outra parte como um documento separado.</p> : null}
      {preview.missing.length ? <p className="libHint"><b>Não encontrados no documento</b> (continuam como estão): {preview.missing.join(", ")}.</p> : null}
      {fields.length ? <div className="kbRow">
        <button type="button" className="ds-button" onClick={() => { setConfirming(false); setSelected(new Set(suggestedKeys(fields))); }}>Selecionar os encontrados (textos)</button>
        <button type="button" className="ds-button" onClick={() => { setConfirming(false); setSelected(new Set()); }}>Limpar seleção</button>
        <small className="libHint">Pilares, pesos, frequência, formatos, plataformas e concorrentes só entram se você marcar um a um.</small>
      </div> : <p className="libHint">A IA não encontrou nenhuma configuração explícita neste documento.</p>}

      {groups.map((g) => <fieldset key={g.id} className="bcImportGroup"><legend>{GROUP_LABELS[g.id]}</legend>
        {g.items.map((f) => <FieldRow key={f.key} field={f} checked={selected.has(f.key)} onToggle={() => toggle(f.key)}
          draft={drafts[f.key]} onDraft={(v) => setDraft(f.key, v)} mode={modes[f.key] || "replace"}
          onMode={(m) => { setConfirming(false); setModes((cur) => ({ ...cur, [f.key]: m })); }} problem={problems[f.key]} />)}
      </fieldset>)}

      {fields.length ? <div className="bcImportApply">
        {!confirming ? <button type="button" className="ds-button is-primary" disabled={!selected.size || blocked || Boolean(busy)} onClick={() => setConfirming(true)}>
          Revisar e aplicar ({selected.size})</button> : <div className="bcConfirm" role="alertdialog" aria-labelledby="bc-confirm-title">
          <p id="bc-confirm-title"><b>Aplicar {selected.size} configuração(ões)?</b> Os valores atuais destes campos serão {Object.values(modes).includes("append") ? "substituídos ou complementados" : "substituídos"}:</p>
          <ul>{fields.filter((f) => selected.has(f.key)).map((f) => <li key={f.key}><b>{f.label}</b>{(modes[f.key] || "replace") === "append" ? " (acrescentar)" : ""}: {describeValue(f, drafts[f.key])}</li>)}</ul>
          <div className="kbRow">
            <button type="button" className="ds-button is-primary" disabled={busy === "apply"} onClick={() => void confirmApply()}>{busy === "apply" ? "Aplicando…" : "Confirmar e aplicar"}</button>
            <button type="button" className="ds-button" disabled={busy === "apply"} onClick={() => setConfirming(false)}>Voltar</button>
          </div>
        </div>}
        {blocked ? <p className="studioWarn" role="status"><AlertTriangle size={14} aria-hidden="true" /> Corrija os campos marcados antes de aplicar.</p> : null}
      </div> : null}
    </div> : null}
  </section>;
}

function FieldRow({ field, checked, onToggle, draft, onDraft, mode, onMode, problem }: {
  field: ImportField; checked: boolean; onToggle: () => void; draft: ImportValue; onDraft: (v: ImportValue) => void;
  mode: Mode; onMode: (m: Mode) => void; problem?: string;
}) {
  const id = `bc-field-${field.key}`;
  const canAppend = (field.kind === "text" || field.kind === "list") && field.key !== "competitors" && field.current !== null;
  return <div className={`bcField is-${field.status}${checked ? " is-checked" : ""}`} data-field={field.key}>
    <div className="bcFieldHead">
      <label htmlFor={id}><input id={id} type="checkbox" checked={checked} onChange={onToggle} /> <b>{field.label}</b></label>
      <span className={`bcBadge is-${field.status}`}>{STATUS_LABELS[field.status]}</span>
      {field.operational ? <span className="bcBadge">Regra operacional</span> : null}
      {!field.changed ? <span className="bcBadge">Igual ao atual</span> : null}
    </div>
    <p className="bcCurrent"><small>Atual:</small> {describeValue(field, field.current)}</p>
    <Editor field={field} value={draft} onChange={onDraft} />
    {canAppend && checked ? <div className="bcMode" role="radiogroup" aria-label={`Como aplicar ${field.label}`}>
      <label><input type="radio" checked={mode === "replace"} onChange={() => onMode("replace")} /> Substituir o atual</label>
      <label><input type="radio" checked={mode === "append"} onChange={() => onMode("append")} /> Acrescentar ao atual</label>
    </div> : null}
    {field.source ? <blockquote className={`bcSource${field.source.verified ? "" : " is-unverified"}`}>
      “{field.source.excerpt}”<small>{field.source.verified ? (field.source.location ? ` — ${field.source.location}` : " — no documento") : " — origem não confirmada no documento"}</small>
    </blockquote> : null}
    {field.notes.map((n, i) => <p key={i} className="bcNote">{n}</p>)}
    {problem ? <p className="studioError" role="alert">{problem}</p> : null}
  </div>;
}

function Editor({ field, value, onChange }: { field: ImportField; value: ImportValue; onChange: (v: ImportValue) => void }) {
  const label = `Novo valor: ${field.label}`;
  if (field.kind === "text") return <textarea rows={3} value={String(value ?? "")} maxLength={field.max_length || undefined}
    onChange={(e) => onChange(e.target.value)} aria-label={label} />;
  if (field.kind === "list") return <input type="text" value={listToText(value)} onChange={(e) => onChange(textToList(e.target.value))}
    aria-label={label} placeholder="Separe por vírgula" />;
  if (field.kind === "int") return <input type="number" min={1} max={14} value={value === null ? "" : Number(value)}
    onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} aria-label={label} />;
  if (field.kind === "channels" || field.kind === "formats") {
    const options = field.kind === "channels" ? STUDIO_CHANNELS : STUDIO_FORMATS;
    const chosen = (value as string[] | null) || [];
    return <div className="bcChecks" role="group" aria-label={label}>{Object.entries(options).map(([k, name]) =>
      <label key={k}><input type="checkbox" checked={chosen.includes(k)}
        onChange={() => onChange(chosen.includes(k) ? chosen.filter((c) => c !== k) : [...chosen, k] as ImportValue)} /> {name}</label>)}</div>;
  }
  if (field.kind === "frequency") {
    const freq = (value as Record<string, number> | null) || {};
    return <div className="bcChecks" role="group" aria-label={label}>{(Object.keys(STUDIO_CHANNELS) as StudioChannel[]).map((c) =>
      <label key={c}>{STUDIO_CHANNELS[c]} <input type="number" min={0} max={14} value={freq[c] ?? ""} aria-label={`Posts por semana no ${STUDIO_CHANNELS[c]}`}
        onChange={(e) => { const next = { ...freq }; const n = Number(e.target.value); if (!e.target.value || n === 0) delete next[c]; else next[c] = n; onChange(next); }} /></label>)}</div>;
  }
  if (field.kind === "competitors") {
    const items = (value as ImportCompetitor[] | null) || [];
    const set = (i: number, patch: Partial<ImportCompetitor>) => onChange(items.map((c, j) => (j === i ? { ...c, ...patch } : c)));
    return <div className="bcPillarEdit" role="group" aria-label={label}>
      {items.map((c, i) => <div key={i} className="bcCompetitorRow">
        <input type="text" value={c.name} maxLength={120} placeholder="Nome" onChange={(e) => set(i, { name: e.target.value })} aria-label={`Nome do concorrente ${i + 1}`} />
        <input type="text" value={c.instagram_handle || ""} maxLength={80} placeholder="@instagram (opcional)" aria-label={`Instagram do concorrente ${i + 1}`}
          onChange={(e) => set(i, { instagram_handle: e.target.value.replace(/^@/, "") || null })} />
        <input type="text" value={c.website || ""} maxLength={500} placeholder="https://site (opcional)" aria-label={`Site do concorrente ${i + 1}`}
          onChange={(e) => set(i, { website: e.target.value || null })} />
        <button type="button" className="kbLink" aria-label={`Tirar concorrente ${i + 1}`} onClick={() => onChange(items.filter((_, j) => j !== i))}><Trash2 size={14} aria-hidden="true" /></button>
      </div>)}
      {items.length < 12 ? <button type="button" className="kbLink" onClick={() => onChange([...items, { name: "", instagram_handle: null, website: null }])}>
        <Plus size={14} aria-hidden="true" /> Adicionar concorrente</button> : null}
    </div>;
  }
  if (field.kind === "pillars") {
    const pillars = (value as ImportPillar[] | null) || [];
    const total = pillarTotal(pillars);
    const set = (i: number, patch: Partial<ImportPillar>) => onChange(pillars.map((p, j) => (j === i ? { ...p, ...patch } : p)));
    return <div className="bcPillarEdit" role="group" aria-label={label}>
      {pillars.map((p, i) => <div key={i} className="bcPillarRow">
        <input type="text" value={p.name} maxLength={80} onChange={(e) => set(i, { name: e.target.value })} aria-label={`Nome do pilar ${i + 1}`} />
        <input type="number" min={0} max={100} value={p.weight ?? ""} placeholder="%" aria-label={`Peso do pilar ${i + 1}`}
          onChange={(e) => set(i, { weight: e.target.value === "" ? null : Number(e.target.value) })} />
        <button type="button" className="kbLink" aria-label={`Tirar pilar ${i + 1}`} onClick={() => onChange(pillars.filter((_, j) => j !== i))}><Trash2 size={14} aria-hidden="true" /></button>
      </div>)}
      {pillars.length < 8 ? <button type="button" className="kbLink" onClick={() => onChange([...pillars, { name: "", weight: null, description: "" }])}>
        <Plus size={14} aria-hidden="true" /> Adicionar pilar</button> : null}
      <small className={total === 100 ? "bcSub" : "bcWarnText"}>Soma dos pesos: {total === null ? "incompleta" : `${total}%`}{total === 100 ? "" : " (precisa fechar 100%)"}</small>
    </div>;
  }
  return null;
}
