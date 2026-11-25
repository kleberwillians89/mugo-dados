import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { usePeriod } from "../../app/PeriodContext";
import { listAssignees, type Person } from "../../app/crm";
import { DEFAULT_DIRECTION, GOAL_METRICS, deleteGoal, goalNumber, saveGoal, suggestGoal, type Goal, type GoalDriver, type GoalInput, type GoalMetric,
  type GoalSuggestion } from "../../app/goals";
import useGoals from "../../hooks/useGoals";
import Drawer from "../Drawer";
import GoalCard from "../GoalCard";
import GoalExplore from "./GoalExplore";
import Premises from "./GoalPremises";
import MainGoal from "./MainGoal";
import GoalAlerts from "./GoalAlerts";
import "../../styles/goals.css";

type Editing = GoalInput & { id?: string };
const toInput = (g: Goal): Editing => ({ id: g.id, metric: g.metric, label: g.label, target_value: g.target_value, period_start: g.period_start, period_end: g.period_end,
  direction: g.direction, is_primary: Boolean(g.is_primary), parent_goal_id: g.parent_goal_id || null, relation: g.relation || null,
  owner_user_id: g.owner_user_id || null, suggestion: g.suggestion || null });

/**
 * Metas da empresa (mesmos registros e endpoints de /metas): "Minha meta" no topo com a leitura executiva,
 * as demais metas e submetas, e o detalhamento (indicadores, cenários, fontes, histórico) sob demanda.
 * Usado na página Metas e na seção Metas do Planejamento. `header` recebe o botão "+ Nova meta" (ou nada).
 */
export default function GoalsPanel({ canManage, header, intro = true }: { canManage: boolean; header: (newButton: ReactNode) => ReactNode; intro?: boolean }) {
  const clientId = getActiveClientId();
  const { period, setPeriod } = usePeriod();
  const model = useGoals(clientId, period.start, period.end);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [removing, setRemoving] = useState<Goal | null>(null);
  const [exploring, setExploring] = useState<Goal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [suggestion, setSuggestion] = useState<GoalSuggestion | null>(null);
  const [suggesting, setSuggesting] = useState(false);

  useEffect(() => { listAssignees().then((r) => setPeople(r.available ? r.people : [])).catch(() => setPeople([])); }, [clientId]);
  const ownerName = (id?: string | null) => (id ? people.find((p) => p.user_id === id)?.name || null : null);
  const main = useMemo(() => model.goals.find((g) => g.is_primary) || model.goals.find((g) => !g.parent_goal_id) || null, [model.goals]);
  const others = model.goals.filter((g) => g.id !== main?.id);
  const labelOf = (id?: string | null) => (id ? model.goals.find((g) => g.id === id)?.label || null : null);

  function startNew(base?: Partial<Editing>) {
    setError(null); setSuggestion(null);
    // Sem valor fictício: o alvo começa vazio (exemplo no campo ou cenário escolhido pela pessoa).
    setEditing({ metric: "revenue", label: "Faturamento", target_value: null, period_start: period.start, period_end: period.end,
      direction: "min", is_primary: !model.goals.length, owner_user_id: null, parent_goal_id: null, relation: null, suggestion: null, ...base });
  }
  function fromDriver(d: GoalDriver, relation: string | null) {
    if (!exploring) return;
    setExploring(null);
    startNew({ metric: d.metric, label: d.label, target_value: d.needed != null ? Math.round(d.needed * 100) / 100 : null, direction: d.direction,
      period_start: exploring.period_start, period_end: exploring.period_end, parent_goal_id: exploring.id, relation, is_primary: false });
  }
  async function askSuggestion() {
    if (!editing) return;
    setSuggesting(true); setSuggestion(null);
    try { setSuggestion(await suggestGoal(editing.metric, editing.period_start, editing.period_end)); }
    catch { setSuggestion({ available: false, reason: "Não foi possível ler o histórico agora. Defina a meta manualmente." }); }
    finally { setSuggesting(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!editing || !canManage || busy || getActiveClientId() !== clientId || !editing.target_value) return;
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

  const newButton = canManage ? <button className="ds-button" onClick={() => startNew()}>+ Nova meta</button> : null;
  const unit = editing ? GOAL_METRICS[editing.metric][1] : "count";
  return <>
    {header(newButton)}
    {intro ? <p>Acompanhe o progresso dos objetivos da empresa.</p> : null}
    <div className="goalFilters"><label>De <input type="date" value={period.start} onChange={(e) => setPeriod({ ...period, start: e.target.value })} /></label><label>Até <input type="date" value={period.end} onChange={(e) => setPeriod({ ...period, end: e.target.value })} /></label></div>
    {model.error || error ? <p role="alert">{error || model.error}</p> : null}
    {model.loading && !model.goals.length ? <p>Carregando metas…</p> : !model.error && !model.goals.length ? <p>Nenhuma meta neste período.</p> : null}
    <GoalAlerts goals={model.goals} onOpen={(goal) => setExploring(goal)} />
    {main ? <MainGoal goal={main} owner={ownerName(main.owner_user_id)} onExplore={() => setExploring(main)} /> : null}
    {others.length ? <div className="goalsGrid">{others.map((goal) => <GoalCard key={goal.id} goal={goal} owner={ownerName(goal.owner_user_id)} parentLabel={labelOf(goal.parent_goal_id)}
      onExplore={() => setExploring(goal)}
      onEdit={canManage ? () => { setError(null); setSuggestion(null); setEditing(toInput(goal)); } : undefined}
      onDelete={canManage ? () => { setError(null); setRemoving(goal); } : undefined} />)}</div> : null}
    {main && canManage ? <div className="goalActions"><button type="button" onClick={() => { setError(null); setSuggestion(null); setEditing(toInput(main)); }}>Editar minha meta</button>
      <button type="button" onClick={() => { setError(null); setRemoving(main); }}>Excluir minha meta</button></div> : null}

    <GoalExplore goal={exploring} onClose={() => setExploring(null)} onCreateSubgoal={canManage ? fromDriver : undefined} ownerName={ownerName}
      people={people} canCreateTasks={canManage} />

    <Drawer open={Boolean(editing)} title={editing?.id ? "Editar meta" : editing?.parent_goal_id ? "Nova submeta" : "Nova meta"} onClose={() => { if (!busy) setEditing(null); }}>
      {editing ? <form onSubmit={submit} className="goalForm">
        {editing.parent_goal_id ? <p className="libHint">Submeta de <b>{labelOf(editing.parent_goal_id)}</b>{editing.relation ? ` · ${editing.relation}` : ""}. Confira o alvo antes de criar.</p> : null}
        <label>Indicador<select value={editing.metric} onChange={(e) => { const metric = e.target.value as GoalMetric; setSuggestion(null);
          setEditing({ ...editing, metric, label: GOAL_METRICS[metric][0], direction: DEFAULT_DIRECTION[metric] || "min", suggestion: null }); }}>
          {Object.entries(GOAL_METRICS).map(([metric, [label]]) => <option key={metric} value={metric}>{label}</option>)}</select></label>
        <label>Nome da meta<input required maxLength={100} value={editing.label} onChange={(e) => setEditing({ ...editing, label: e.target.value })} /></label>
        <label>Tipo de meta<select value={editing.direction || "min"} onChange={(e) => setEditing({ ...editing, direction: e.target.value as "min" | "max" })}>
          <option value="min">Mínima: atingir ou superar</option><option value="max">Máxima: não passar de (teto)</option></select></label>
        <label>{editing.direction === "max" ? "Teto" : "Objetivo"} ({unit === "currency" ? "R$" : unit === "multiple" ? "x" : unit === "percent" ? "%" : "quantidade"})
          <input type="number" min="0.01" step="any" required value={editing.target_value ?? ""} placeholder={unit === "currency" ? "Ex.: 80000" : "Ex.: 300"}
            onChange={(e) => setEditing({ ...editing, target_value: e.target.value === "" ? null : Number(e.target.value), suggestion: null })} /></label>
        <div className="goalSuggest">
          <button type="button" className="ds-button" disabled={suggesting} onClick={() => void askSuggestion()}>{suggesting ? "Lendo o histórico…" : "Sugerir meta"}</button>
          <small>Opcional: cenários a partir do histórico. Você escolhe, ajusta ou ignora.</small>
          {suggestion ? !suggestion.available ? <p className="libHint">{suggestion.reason}</p> : <div className="goalScenarioPick" role="group" aria-label="Cenários sugeridos">
            {suggestion.scenarios!.map((s) => <button type="button" key={s.key} className={editing.suggestion?.key === s.key ? "is-active" : ""}
              onClick={() => setEditing({ ...editing, target_value: Math.round(s.value * 100) / 100,
                suggestion: { key: s.key, label: s.label, value: s.value, premises: suggestion.premises, uncertainty: suggestion.uncertainty || "" } })}>
              <small>{s.label}</small><b>{goalNumber(s.value, editing.metric)}</b></button>)}
            <small>Incerteza {suggestion.uncertainty}.</small>
          </div> : null}
          {suggestion?.premises ? <Premises premises={suggestion.premises} format={(v) => goalNumber(v, editing.metric)} /> : null}
        </div>
        <label>Início<input type="date" required value={editing.period_start} onChange={(e) => setEditing({ ...editing, period_start: e.target.value })} /></label>
        <label>Fim<input type="date" required min={editing.period_start} value={editing.period_end} onChange={(e) => setEditing({ ...editing, period_end: e.target.value })} /></label>
        {people.length ? <label>Responsável (opcional)<select value={editing.owner_user_id || ""} onChange={(e) => setEditing({ ...editing, owner_user_id: e.target.value || null })}>
          <option value="">Sem responsável</option>{people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}</select>
          <small>Acompanha a meta e propõe ações; não ganha permissão para mudar objetivos ou integrações.</small></label> : null}
        {!editing.parent_goal_id ? <label className="goalCheck"><input type="checkbox" checked={Boolean(editing.is_primary)} onChange={(e) => setEditing({ ...editing, is_primary: e.target.checked })} /> Meta principal (aparece em "Minha meta")</label> : null}
        {error ? <p role="alert">{error}</p> : null}<div className="goalActions"><button type="button" disabled={busy} onClick={() => setEditing(null)}>Cancelar</button><button className="ds-button" disabled={busy || !editing.target_value}>{busy ? "Salvando…" : editing.id ? "Salvar meta" : "Criar meta"}</button></div>
      </form> : null}
    </Drawer>
    <Drawer open={Boolean(removing)} title="Excluir meta" onClose={() => { if (!busy) setRemoving(null); }}><p>Excluir a meta “{removing?.label}”? Ela continua registrada no histórico.</p>{error ? <p role="alert">{error}</p> : null}<div className="goalActions"><button disabled={busy} onClick={() => setRemoving(null)}>Cancelar</button><button disabled={busy} onClick={() => void remove()}>Excluir meta</button></div></Drawer>
  </>;
}
