import { useState, type FormEvent, type ReactNode } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { usePeriod } from "../../app/PeriodContext";
import { GOAL_METRICS, saveGoal, deleteGoal, type Goal, type GoalInput, type GoalMetric } from "../../app/goals";
import useGoals from "../../hooks/useGoals";
import Drawer from "../Drawer";
import GoalCard from "../GoalCard";
import "../../styles/goals.css";
/**
 * Metas da empresa (mesmos registros e endpoints de /metas): progresso medido, criar, editar e excluir.
 * Usado na página Metas e na seção Metas do Planejamento. `header` recebe o botão "+ Nova meta" (ou nada).
 */
export default function GoalsPanel({ canManage, header, intro = true }: { canManage: boolean; header: (newButton: ReactNode) => ReactNode; intro?: boolean }) {
  const clientId = getActiveClientId();
  const { period, setPeriod } = usePeriod();
  const model = useGoals(clientId, period.start, period.end);
  const [editing, setEditing] = useState<GoalInput & { id?: string } | null>(null);
  const [removing, setRemoving] = useState<Goal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!editing || !canManage || busy || getActiveClientId() !== clientId) return;
    setBusy(true); setError(null);
    try { const { id, ...input } = editing; await saveGoal(input, id); if (getActiveClientId() !== clientId) return; setEditing(null); await model.reload(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar a meta."); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!removing || !canManage || busy || getActiveClientId() !== clientId) return;
    setBusy(true); setError(null);
    try { await deleteGoal(removing.id); if (getActiveClientId() !== clientId) return; setRemoving(null); await model.reload(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível excluir a meta."); }
    finally { setBusy(false); }
  }
  const newButton = canManage ? <button className="ds-button" onClick={() => { setError(null); setEditing({ metric: "revenue", label: "Faturamento", target_value: 50000, period_start: period.start, period_end: period.end }); }}>+ Nova meta</button> : null;
  return <>
    {header(newButton)}
    {intro ? <p>Acompanhe o progresso dos objetivos da empresa.</p> : null}
    <div className="goalFilters"><label>De <input type="date" value={period.start} onChange={(e) => setPeriod({ ...period, start: e.target.value })} /></label><label>Até <input type="date" value={period.end} onChange={(e) => setPeriod({ ...period, end: e.target.value })} /></label></div>
    {model.error || error ? <p role="alert">{error || model.error}</p> : null}
    {model.loading && !model.goals.length ? <p>Carregando metas…</p> : !model.error && !model.goals.length ? <p>Nenhuma meta neste período.</p> : null}
    <div className="goalsGrid">{model.goals.map((goal) => <GoalCard key={goal.id} goal={goal} onEdit={canManage ? () => { setError(null); setEditing({ id: goal.id, metric: goal.metric, label: goal.label, target_value: goal.target_value, period_start: goal.period_start, period_end: goal.period_end }); } : undefined} onDelete={canManage ? () => { setError(null); setRemoving(goal); } : undefined} />)}</div>
    <Drawer open={Boolean(editing)} title={editing?.id ? "Editar meta" : "Nova meta"} onClose={() => { if (!busy) setEditing(null); }}>
      {editing ? <form onSubmit={submit} className="goalForm">
        <label>Indicador<select value={editing.metric} onChange={(e) => { const metric = e.target.value as GoalMetric; setEditing({ ...editing, metric, label: GOAL_METRICS[metric][0] }); }}>{Object.entries(GOAL_METRICS).map(([metric, [label]]) => <option key={metric} value={metric}>{label}</option>)}</select></label>
        <label>Nome da meta<input required maxLength={100} value={editing.label} onChange={(e) => setEditing({ ...editing, label: e.target.value })} /></label>
        <label>Objetivo ({GOAL_METRICS[editing.metric][1] === "currency" ? "R$" : GOAL_METRICS[editing.metric][1] === "multiple" ? "x" : "quantidade"})<input type="number" min="0.01" step="any" required value={editing.target_value} onChange={(e) => setEditing({ ...editing, target_value: Number(e.target.value) })} /></label>
        <label>Início<input type="date" required value={editing.period_start} onChange={(e) => setEditing({ ...editing, period_start: e.target.value })} /></label>
        <label>Fim<input type="date" required min={editing.period_start} value={editing.period_end} onChange={(e) => setEditing({ ...editing, period_end: e.target.value })} /></label>
        {error ? <p role="alert">{error}</p> : null}<div className="goalActions"><button type="button" disabled={busy} onClick={() => setEditing(null)}>Cancelar</button><button className="ds-button" disabled={busy}>{busy ? "Salvando…" : editing.id ? "Salvar meta" : "Criar meta"}</button></div>
      </form> : null}
    </Drawer>
    <Drawer open={Boolean(removing)} title="Excluir meta" onClose={() => { if (!busy) setRemoving(null); }}><p>Excluir a meta “{removing?.label}”?</p>{error ? <p role="alert">{error}</p> : null}<div className="goalActions"><button disabled={busy} onClick={() => setRemoving(null)}>Cancelar</button><button disabled={busy} onClick={() => void remove()}>Excluir meta</button></div></Drawer>
  </>;
}
