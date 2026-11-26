import { useEffect, useState } from "react";
import { getGoalDiagnosis, recommendGoal, taskFromRecommendation, type Goal, type GoalDiagnosis, type GoalRecommendation } from "../../app/goals";
import type { Person } from "../../app/crm";

const TIPO: Record<string, string> = { recomendacao: "Recomendação", estimativa: "Estimativa", investigacao: "Investigar" };

/**
 * Diagnóstico do desvio (fatos e, quando sustentada, uma hipótese) e "Analisar oportunidades de melhoria" (IA, no clique).
 * Cada recomendação mostra evidência e justificativa; vira tarefa no Kanban só quando a pessoa confirma responsável e prazo.
 */
export default function GoalActions({ goal, people, canCreateTasks }: { goal: Goal; people: Person[]; canCreateTasks: boolean }) {
  const [diag, setDiag] = useState<GoalDiagnosis | null>(null);
  const [constraints, setConstraints] = useState("");
  const [rec, setRec] = useState<GoalRecommendation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taskFor, setTaskFor] = useState<number | null>(null);
  const [who, setWho] = useState("");
  const [due, setDue] = useState("");

  useEffect(() => {
    let alive = true;
    getGoalDiagnosis(goal.id).then((d) => { if (alive) setDiag(d); }).catch(() => { if (alive) setDiag({ available: false, reason: "Não foi possível ler o diagnóstico agora." }); });
    return () => { alive = false; };
  }, [goal.id]);

  async function analyze() {
    setBusy(true); setError(null);
    try { setRec(await recommendGoal(goal.id, constraints)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "A IA não conseguiu analisar agora."); }
    finally { setBusy(false); }
  }
  async function createTask(index: number) {
    if (!rec?.id) return;
    setBusy(true); setError(null);
    try {
      const out = await taskFromRecommendation(goal.id, rec.id, index, { assignee_user_ids: who ? [who] : [], due_date: due || null });
      setRec({ ...rec, items: rec.items.map((item, i) => (i === index ? { ...item, task_id: out.task_id } : item)) });
      setTaskFor(null); setWho(""); setDue("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível criar a tarefa."); }
    finally { setBusy(false); }
  }

  return <div className="goalDiag">
    <strong>Diagnóstico</strong>
    {!diag ? <p className="libHint">Lendo os números…</p> : !diag.available ? <p className="libHint">{diag.reason}</p> : <>
      {diag.periods ? <small>Comparação entre {diag.periods[0][0].split("-").reverse().join("/")}–{diag.periods[0][1].split("-").reverse().join("/")} e {diag.periods[1][0].split("-").reverse().join("/")}–{diag.periods[1][1].split("-").reverse().join("/")}.</small> : null}
      <ul>{diag.facts!.map((f) => <li key={f}><span className="goalTag">Fato</span>{f}</li>)}</ul>
      {diag.hypothesis ? <p><span className="goalTag is-hipotese">Hipótese</span>{diag.hypothesis}</p> : null}
    </>}

    <label className="goalConstraints">Restrições para a análise (opcional)
      <textarea rows={2} maxLength={1000} value={constraints} placeholder="Ex.: sem aumentar a verba; não mexer no preço" onChange={(e) => setConstraints(e.target.value)} /></label>
    <button type="button" className="ds-button" disabled={busy} onClick={() => void analyze()} style={{ justifySelf: "start" }}>
      {busy && !rec ? "Analisando…" : "Analisar oportunidades de melhoria"}</button>
    <small>A IA analisa e recomenda; nada é executado. Você escolhe o que vira tarefa.</small>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {rec ? <>
      {rec.leitura ? <p>{rec.leitura}</p> : null}
      <ol className="goalRecs">{rec.items.map((item, index) => <li key={index}>
        <strong><span className={`goalTag is-${item.tipo}`}>{TIPO[item.tipo] || "Recomendação"}</span>{item.titulo}</strong>
        <span>{item.acao}</span>
        <small>Evidência: {item.evidencia}</small><small>Por quê: {item.justificativa}</small>
        {item.task_id ? <small className="studioOk">Virou tarefa no Kanban.</small>
          : !canCreateTasks ? null : !rec.saved ? <small>Para virar tarefa, a recomendação precisa estar registrada (histórico de recomendações indisponível).</small>
          : taskFor === index ? <div className="goalTaskForm">
            {people.length ? <label>Responsável<select value={who} onChange={(e) => setWho(e.target.value)}><option value="">Escolha…</option>
              {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}</select></label> : null}
            <label>Prazo<input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label>
            <span style={{ display: "flex", gap: 8 }}>
              <button type="button" className="ds-button is-primary" disabled={busy || (people.length > 0 && !who) || !due} onClick={() => void createTask(index)}>Confirmar e criar tarefa</button>
              <button type="button" className="ds-button" onClick={() => setTaskFor(null)}>Cancelar</button></span>
          </div> : <button type="button" className="ds-button" style={{ justifySelf: "start" }} onClick={() => { setTaskFor(index); setWho(""); setDue(""); }}>Criar tarefa</button>}
      </li>)}</ol>
    </> : null}
  </div>;
}
