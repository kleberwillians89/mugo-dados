import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { listAssignees, type Person } from "../../app/crm";
import { BRIEFING_ROLES, CONTENT_ANGLES, CREATIVE_DIRECTION_FIELDS, briefingText, cleanDirection, sendBriefing, type BriefingRole, type CalendarItem,
  type CreativeDirection as Direction, type StudioBriefing } from "../../app/studio";
import type { PieceDraft } from "../../app/studioCalendar";
import CreativeDirection from "./CreativeDirection";

type TextKey = "summary" | "objective" | "key_message" | "tone" | "target_audience";
const TEXT_FIELDS: { key: TextKey; label: string; rows: number }[] = [
  { key: "summary", label: "Resumo", rows: 2 }, { key: "objective", label: "Objetivo", rows: 2 }, { key: "key_message", label: "Mensagem central", rows: 2 },
  { key: "tone", label: "Tom", rows: 1 }, { key: "target_audience", label: "Público", rows: 2 },
];
const lines = (v?: string[]) => (v || []).join("\n");
const toList = (text: string) => text.split("\n");

// Página do briefing editável "como Word": o texto fica igual ao de leitura (sem caixa), cresce com o conteúdo.
const DOC_TEXT: CSSProperties = { display: "block", width: "100%", border: 0, background: "transparent", resize: "none", overflow: "hidden",
  font: "inherit", color: "inherit", lineHeight: "inherit", padding: "2px 0", margin: 0, outline: "none" };
const DOC_SELECT: CSSProperties = { border: 0, background: "transparent", font: "inherit", color: "inherit", padding: "2px 0" };

function DocText({ label, value, onChange, disabled, placeholder = "Escreva aqui…" }: { label: string; value: string; onChange: (v: string) => void;
  disabled?: boolean; placeholder?: string }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useLayoutEffect(() => { const el = ref.current; if (el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; } }, [value]);
  return <textarea ref={ref} rows={1} aria-label={label} style={DOC_TEXT} value={value} placeholder={placeholder} disabled={disabled}
    onChange={(e) => onChange(e.target.value)} />;
}

/** Briefing da peça (primeiro bloco da janela): ler, copiar, enviar para quem vai fazer e, pelo botão
 *  "Editar peça", abrir a edição do direcionamento criativo. A geração de briefing com IA saiu desta janela. */
export default function BriefingPanel({ item, hook, disabled, pending, piece, onPiece, direction, onDirection }: { item: CalendarItem; hook?: string; disabled?: boolean;
  /** O Direcionamento Criativo mudou e não foi salvo: a tarefa leva o que está salvo. */
  pending?: boolean;
  /** Rascunho do briefing da peça e do direcionamento: com eles, o bloco é uma página editável (salva com a pauta). */
  piece?: PieceDraft; onPiece?: (next: PieceDraft) => void;
  direction?: Direction; onDirection?: (next: Direction) => void }) {
  const current = item;
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  // Enviar para alguém: vira tarefa da pessoa, só com o que a função dela precisa.
  const [sending, setSending] = useState(false);
  const [people, setPeople] = useState<Person[] | null>(null);
  const [to, setTo] = useState<{ role: BriefingRole; user: string; due: string; note: string }>({ role: "designer", user: "", due: "", note: "" });
  const [sendBusy, setSendBusy] = useState(false);
  const [sent, setSent] = useState<string[]>([]);
  useEffect(() => {
    if (!sending || people) return;
    listAssignees().then((r) => setPeople(r.available ? r.people : [])).catch(() => setPeople([]));
  }, [sending, people]);
  const send = async () => {
    const person = (people || []).find((p) => p.user_id === to.user);
    setSendBusy(true); setError("");
    try {
      await sendBriefing(current.id, { role: to.role, assignee_user_id: person?.user_id || null, assignee_name: person?.name || null,
        due_date: to.due || null, note: to.note.trim() || null });
      setSent((list) => [...list, `${person?.name || BRIEFING_ROLES[to.role]} (${BRIEFING_ROLES[to.role]})`]);
      setTo({ ...to, user: "", note: "" });
    } catch (e) { setError(e instanceof Error ? e.message : "Não foi possível enviar o briefing."); }
    finally { setSendBusy(false); }
  };
  const b = current.signals?.briefing || {};
  const hasBriefing = Boolean(current.script || current.visual_idea || Object.keys(b).length);
  const hasDirection = Object.keys(cleanDirection(current.creative_direction)).length > 0;
  const has = hasBriefing || hasDirection;
  const copy = async () => {
    try { await navigator.clipboard.writeText(briefingText({ ...current, hook: hook || current.hook })); setCopied(true); window.setTimeout(() => setCopied(false), 2500); }
    catch { /* navegador sem permissão de copiar */ }
  };
  const row = (label: string, value?: string | null) => value ? <div><b>{label}</b><p>{value}</p></div> : null;
  const saved = cleanDirection(current.creative_direction);

  const canEdit = Boolean(piece && onPiece);
  const setBrief = (patch: Partial<StudioBriefing>) => { if (piece && onPiece) onPiece({ ...piece, briefing: { ...piece.briefing, ...patch } }); };
  const angles = piece?.briefing.angle && !CONTENT_ANGLES[piece.briefing.angle] ? { [piece.briefing.angle]: piece.briefing.angle, ...CONTENT_ANGLES } : CONTENT_ANGLES;

  return <details className="postFromMatrix postBriefing" open>
    <summary>Briefing da peça</summary>
    {canEdit && piece && onPiece ? <div className="postBriefingDoc" aria-label="Briefing da peça (editável)">
      {direction && onDirection ? CREATIVE_DIRECTION_FIELDS.map((f) => <div key={f.key}><b>{f.label}</b>
        <DocText label={f.label} value={direction[f.key] || ""} disabled={disabled} onChange={(v) => onDirection({ ...direction, [f.key]: v })} /></div>) : null}
      <div><b>Ângulo</b><select style={DOC_SELECT} aria-label="Ângulo" value={piece.briefing.angle || ""} disabled={disabled} onChange={(e) => setBrief({ angle: e.target.value })}>
        <option value="">Sem ângulo</option>
        {Object.entries(angles).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></div>
      {TEXT_FIELDS.map((f) => <div key={f.key}><b>{f.label}</b>
        <DocText label={f.label} value={piece.briefing[f.key] || ""} disabled={disabled} onChange={(v) => setBrief({ [f.key]: v })} /></div>)}
      <div><b>Entregáveis</b><DocText label="Entregáveis" value={lines(piece.briefing.deliverables)} disabled={disabled} placeholder="Um por linha"
        onChange={(v) => setBrief({ deliverables: toList(v) })} /></div>
      <div><b>Requisitos técnicos</b><DocText label="Requisitos técnicos" value={lines(piece.briefing.tech_requirements)} disabled={disabled} placeholder="Um por linha"
        onChange={(v) => setBrief({ tech_requirements: toList(v) })} /></div>
      <div><b>Roteiro</b><DocText label="Roteiro" value={piece.script} disabled={disabled} onChange={(v) => onPiece({ ...piece, script: v })} /></div>
      <div><b>Direção da arte</b><DocText label="Direção da arte" value={piece.visual_idea} disabled={disabled} onChange={(v) => onPiece({ ...piece, visual_idea: v })} /></div>
      {direction && onDirection ? <CreativeDirection embedded aiOnly value={direction} onChange={onDirection} itemId={item.id} disabled={disabled}
        fromMatrix={item.origin === "matriz"} /> : null}
    </div> : <>
    {CREATIVE_DIRECTION_FIELDS.map((f) => <div key={f.key}>{row(f.label, saved[f.key])}</div>)}
    {hasBriefing ? <>
      {row("Ângulo", b.angle ? CONTENT_ANGLES[b.angle] || b.angle : null)}
      {row("Resumo", b.summary)}
      {row("Objetivo", b.objective)}
      {row("Mensagem central", b.key_message)}
      {row("Tom", b.tone)}
      {row("Público", b.target_audience)}
      {b.deliverables?.length ? <div><b>Entregáveis</b><ul>{b.deliverables.map((d) => <li key={d}>{d}</li>)}</ul></div> : null}
      {b.tech_requirements?.length ? <div><b>Requisitos técnicos</b><ul>{b.tech_requirements.map((d) => <li key={d}>{d}</li>)}</ul></div> : null}
      {row("Roteiro", current.script)}
      {row("Direção da arte", current.visual_idea)}
    </> : hasDirection ? null : <p className="postBriefingEmpty">Esta peça ainda não tem briefing. Escreva o que quem cria precisa saber.</p>}
    </>}
    <div className="postBriefingActions">
      {has ? <button type="button" className="ds-button" onClick={() => void copy()}>{copied ? "Briefing copiado ✓" : "Copiar briefing"}</button> : null}
      {has && !sending ? <button type="button" className="ds-button" disabled={disabled} onClick={() => setSending(true)}>Enviar para…</button> : null}
    </div>
    {sending && pending ? <small className="postArtHint is-pending">O Direcionamento Criativo mudou: salve antes de enviar, a tarefa leva o que está salvo.</small> : null}
    {sending ? <div className="postBriefingForm briefingSend">
      <small>Enviar o briefing: vira tarefa da pessoa, só com o que a função dela precisa.</small>
      <label>Função<select value={to.role} onChange={(e) => setTo({ ...to, role: e.target.value as BriefingRole })}>
        {(Object.keys(BRIEFING_ROLES) as BriefingRole[]).map((r) => <option key={r} value={r}>{BRIEFING_ROLES[r]}</option>)}</select></label>
      <label>Pessoa<select value={to.user} onChange={(e) => setTo({ ...to, user: e.target.value })} disabled={people === null}>
        <option value="">{people === null ? "Carregando…" : people.length ? "Escolha quem vai fazer" : "Sem integrantes: fica sem responsável"}</option>
        {(people || []).map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}</select></label>
      <label>Prazo<input type="date" value={to.due} onChange={(e) => setTo({ ...to, due: e.target.value })} /><small>Vazio: 2 dias antes da publicação.</small></label>
      <label>Recado<textarea rows={2} maxLength={600} value={to.note} placeholder="Algo a mais para esta pessoa" onChange={(e) => setTo({ ...to, note: e.target.value })} /></label>
      <div className="postBriefingActions">
        <button type="button" className="ds-button is-primary" disabled={sendBusy || (people !== null && people.length > 0 && !to.user)} onClick={() => void send()}>{sendBusy ? "Enviando…" : "Enviar briefing"}</button>
        <button type="button" className="ds-button" onClick={() => setSending(false)}>Fechar</button>
      </div>
      {sent.length ? <p className="studioOk">✓ Enviado para {sent.join(", ")}. Já está nas Tarefas de cada um.</p> : null}
    </div> : null}
    {error ? <small className="studioError">{error}</small> : null}
  </details>;
}
