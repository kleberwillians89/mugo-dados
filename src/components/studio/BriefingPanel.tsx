import { useEffect, useState } from "react";
import { listAssignees, type Person } from "../../app/crm";
import { BOLDNESS_LABELS, BRIEFING_ROLES, CONTENT_ANGLES, briefingText, generateBriefing, sendBriefing, type BriefingDirection, type BriefingRole, type CalendarItem } from "../../app/studio";

/** Briefing da peça (fluxo do Atendimento do iAgência): ler, copiar e gerar/refazer com a IA, com direcionamento opcional. */
export default function BriefingPanel({ item, hook, disabled }: { item: CalendarItem; hook?: string; disabled?: boolean }) {
  const [current, setCurrent] = useState<CalendarItem>(item);
  const [open, setOpen] = useState(false);
  const [direction, setDirection] = useState<BriefingDirection>({ boldness: 3 });
  const [busy, setBusy] = useState(false);
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
      {has && !sending ? <button type="button" className="ds-button" onClick={() => setSending(true)}>Enviar para…</button> : null}
    </div>
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
