import { useEffect, useState } from "react";
import { listAssignees, type Person } from "../../app/crm";
import { BRIEFING_ROLES, CONTENT_ANGLES, briefingText, cleanDirection, sendBriefing, type BriefingRole, type CalendarItem } from "../../app/studio";

/** Briefing da peça: ler, copiar e enviar para quem vai fazer (vira tarefa com o Direcionamento Criativo salvo).
 *  A geração de briefing com IA saiu desta janela: a orientação da peça agora é o Direcionamento Criativo, no topo. */
export default function BriefingPanel({ item, hook, disabled, pending }: { item: CalendarItem; hook?: string; disabled?: boolean;
  /** O Direcionamento Criativo mudou e não foi salvo: a tarefa leva o que está salvo. */
  pending?: boolean }) {
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

  return <details className="postFromMatrix postBriefing" open>
    <summary>Briefing da peça</summary>
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
    </> : <p className="postBriefingEmpty">{hasDirection ? "O Direcionamento Criativo salvo (no topo) é o que vai para quem cria." : "Escreva o Direcionamento Criativo no topo e salve: é ele que vai para quem cria."}</p>}
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
