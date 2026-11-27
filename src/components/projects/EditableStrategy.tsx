import { useEffect, useRef, useState } from "react";
import { updateProject, type Project, type ProjectInputs, type StrategyPlan } from "../../app/projects";

const TEXT_FIELDS: { key: keyof Pick<StrategyPlan, "big_idea" | "context" | "challenge" | "insight" | "strategy">; label: string; rows: number }[] = [
  { key: "big_idea", label: "Grande ideia", rows: 2 }, { key: "context", label: "Contexto", rows: 3 }, { key: "challenge", label: "Desafio", rows: 2 },
  { key: "insight", label: "Insight", rows: 2 }, { key: "strategy", label: "Estratégia", rows: 4 },
];
const INPUT_FIELDS: { key: keyof Pick<ProjectInputs, "objective" | "audience" | "budget">; label: string }[] = [
  { key: "objective", label: "Objetivo de negócio" }, { key: "audience", label: "Público" }, { key: "budget", label: "Verba" },
];
const SAVE_DELAY = 1200;
type Draft = { text: Record<string, string>; inputs: Record<string, string> };

function fromProject(p: Project): Draft {
  const plan = (p.plan || {}) as StrategyPlan;
  const inputs = p.inputs || {};
  return { text: Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, String(plan[f.key] || "")])),
    inputs: Object.fromEntries(INPUT_FIELDS.map((f) => [f.key, String(inputs[f.key] || "")])) };
}
const same = (a: Draft, b: Draft) => JSON.stringify(a) === JSON.stringify(b);

/**
 * Planejamento editável com salvamento automático (sem botão "Salvar"): objetivo, público, verba e os textos do plano.
 * Mostra quando foi salvo. Refazer com IA ou restaurar uma versão substitui o rascunho pelo conteúdo novo.
 * Listas (mensagens, canais, fases, KPIs, riscos) seguem como estão: mude pedindo à IA ou restaurando uma versão.
 */
export default function EditableStrategy({ project, onSaved, disabled }: { project: Project; onSaved: (p: Project) => void; disabled?: boolean }) {
  const [draft, setDraft] = useState<Draft>(() => fromProject(project));
  const [state, setState] = useState<{ kind: "idle" | "saving" | "saved" | "error"; at?: string }>({ kind: "idle" });
  const [base, setBase] = useState<Draft>(() => fromProject(project));  // o que já está salvo
  const onSavedRef = useRef(onSaved);
  useEffect(() => { onSavedRef.current = onSaved; }, [onSaved]);

  // Conteúdo novo vindo de fora (IA refez, versão restaurada): troca o rascunho se não houver edição pendente.
  const incoming = fromProject(project);
  if (!same(incoming, base) && same(draft, base)) {
    setBase(incoming);
    setDraft(incoming);
  }

  useEffect(() => {
    if (same(draft, base)) return undefined;
    const timer = window.setTimeout(async () => {
      setState({ kind: "saving" });
      const plan = { ...(project.plan || {}), ...Object.fromEntries(Object.entries(draft.text)) };
      const inputs = { ...(project.inputs || {}), ...Object.fromEntries(Object.entries(draft.inputs)) };
      try {
        const r = await updateProject("planejamento", project.id, { plan, inputs });
        setBase(draft);
        setState({ kind: "saved", at: new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) });
        onSavedRef.current(r.project);
      } catch { setState({ kind: "error" }); }
    }, SAVE_DELAY);
    return () => window.clearTimeout(timer);
  }, [draft, base, project.id, project.plan, project.inputs]);

  const plan = (project.plan || {}) as StrategyPlan;
  const status = state.kind === "saving" ? "Salvando…" : state.kind === "saved" ? `Salvo às ${state.at}` : state.kind === "error"
    ? "Não foi possível salvar. Suas alterações continuam aqui; tente de novo em instantes." : same(draft, base) ? "Tudo salvo" : "Alterações pendentes…";

  return <div className="projStrategy projEditable">
    <p className={`projSaveState is-${state.kind}`} role="status" aria-live="polite">{status}</p>
    <fieldset disabled={disabled} className="projEditFields">
      <div className="projEditInputs">{INPUT_FIELDS.map((f) => <label key={f.key}>{f.label}
        <input value={draft.inputs[f.key]} maxLength={600} onChange={(e) => setDraft((d) => ({ ...d, inputs: { ...d.inputs, [f.key]: e.target.value } }))} /></label>)}</div>
      {TEXT_FIELDS.map((f) => <label key={f.key}>{f.label}
        <textarea rows={f.rows} value={draft.text[f.key]} maxLength={4000} onChange={(e) => setDraft((d) => ({ ...d, text: { ...d.text, [f.key]: e.target.value } }))} /></label>)}
    </fieldset>
    <dl className="briefFacts">
      {plan.messages?.length ? <><dt>Mensagens</dt><dd><ul>{plan.messages.map((m) => <li key={m}>{m}</li>)}</ul></dd></> : null}
      {plan.channels?.length ? <><dt>Canais</dt><dd><ul>{plan.channels.map((c) => <li key={c.channel}><b>{c.channel}</b>: {c.role}</li>)}</ul></dd></> : null}
    </dl>
    {plan.phases?.length ? <><h3>Fases</h3><ol className="projPhases">{plan.phases.map((f) => <li key={f.phase}><b>{f.phase}</b><small>{f.when}</small><span>{f.what}</span></li>)}</ol></> : null}
    {plan.kpis?.length ? <><h3>KPIs</h3><ul className="projKpis">{plan.kpis.map((k) => <li key={k.kpi}><small>{k.kpi}</small><b>{k.target}</b></li>)}</ul></> : null}
    {plan.risks?.length ? <><h3>Riscos</h3><ul className="projList">{plan.risks.map((r) => <li key={r}>{r}</li>)}</ul></> : null}
  </div>;
}
