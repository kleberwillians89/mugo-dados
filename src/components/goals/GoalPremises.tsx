import type { GoalSuggestion } from "../../app/goals";

/** Premissas de uma sugestão de meta: períodos usados, cobertura, modelo e alerta de sazonalidade. */
export default function Premises({ premises, format }: { premises: NonNullable<GoalSuggestion["premises"]>; format: (v: number | null) => string }) {
  return <div className="goalPremises">
    <strong>Premissas</strong>
    <p className="libHint">{premises.model}</p>
    <ul>{premises.history.map((h) => <li key={h.start}>{h.start.split("-").reverse().join("/")} a {h.end.split("-").reverse().join("/")}: {h.value != null ? format(h.value) : "sem dado"}
      {" "}· cobertura {Math.round(h.coverage * 100)}%{h.coverage < 0.8 ? " (não usado)" : ""}</li>)}</ul>
    {premises.seasonality_note ? <p className="goalWarn">{premises.seasonality_note}</p> : null}
  </div>;
}
