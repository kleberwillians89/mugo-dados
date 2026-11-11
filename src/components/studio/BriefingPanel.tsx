import { useState } from "react";
import { BOLDNESS_LABELS, CONTENT_ANGLES, briefingText, generateBriefing, type BriefingDirection, type CalendarItem } from "../../app/studio";

/** Briefing da peça (fluxo do Atendimento do iAgência): ler, copiar e gerar/refazer com a IA, com direcionamento opcional. */
export default function BriefingPanel({ item, hook, disabled }: { item: CalendarItem; hook?: string; disabled?: boolean }) {
  const [current, setCurrent] = useState<CalendarItem>(item);
  const [open, setOpen] = useState(false);
  const [direction, setDirection] = useState<BriefingDirection>({ boldness: 3 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const b = current.signals?.briefing || {};
  const has = Boolean(current.script || current.visual_idea || Object.keys(b).length);
  const set = (patch: BriefingDirection) => setDirection((d) => ({ ...d, ...patch }));

  const run = async () => {
    setBusy(true); setError("");
    try { const res = await generateBriefing(current.id, direction); setCurrent({ ...current, ...res.item }); setOpen(false); }
    catch (e) { setError(e instanceof Error ? e.message : "Não foi possível gerar o briefing."); }
    finally { setBusy(false); }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(briefingText({ ...current, hook: hook || current.hook })); setCopied(true); window.setTimeout(() => setCopied(false), 2500); }
    catch { /* navegador sem permissão de copiar */ }
  };
  const row = (label: string, value?: string | null) => value ? <div><b>{label}</b><p>{value}</p></div> : null;

  return <details className="postFromMatrix postBriefing" open>
    <summary>Briefing da peça</summary>
    {has ? <>
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
    </> : <p className="postBriefingEmpty">Esta pauta ainda não tem briefing. Gere com a IA: ela usa o perfil da marca, o que já performou, o que o cliente aprovou e as referências do post.</p>}
    <div className="postBriefingActions">
      {has ? <button type="button" className="ds-button" onClick={() => void copy()}>{copied ? "Briefing copiado ✓" : "Copiar briefing"}</button> : null}
      <button type="button" className="ds-button is-primary" disabled={busy || disabled} onClick={() => (open ? void run() : setOpen(true))}>
        {busy ? "Gerando briefing…" : open ? "Gerar agora" : has ? "Refazer com IA" : "Gerar briefing com IA"}</button>
      {open && !busy ? <button type="button" className="ds-button" onClick={() => setOpen(false)}>Cancelar</button> : null}
    </div>
    {open ? <div className="postBriefingForm">
      <small>Direcionamento (opcional, como no Atendimento do iAgência):</small>
      <label>Objetivo<input maxLength={600} value={direction.objective || ""} placeholder="Ex.: gerar comentários, levar ao link" onChange={(e) => set({ objective: e.target.value })} /></label>
      <label>Público<input maxLength={600} value={direction.target_audience || ""} placeholder="Ex.: quem já comprou split" onChange={(e) => set({ target_audience: e.target.value })} /></label>
      <label>CTA<input maxLength={300} value={direction.cta || ""} placeholder="Ex.: comenta o perfume que você quer" onChange={(e) => set({ cta: e.target.value })} /></label>
      <label>Ousadia: <b>{BOLDNESS_LABELS[direction.boldness || 3]}</b>
        <input type="range" min={1} max={5} value={direction.boldness || 3} onChange={(e) => set({ boldness: Number(e.target.value) })} /></label>
      <label>Referências<input maxLength={600} value={direction.references || ""} placeholder="Link ou descrição do estilo" onChange={(e) => set({ references: e.target.value })} /></label>
      <label>Pedido<textarea rows={2} maxLength={600} value={direction.request || ""} placeholder="O que mais a IA precisa saber" onChange={(e) => set({ request: e.target.value })} /></label>
    </div> : null}
    {error ? <small className="studioError">{error}</small> : null}
  </details>;
}
