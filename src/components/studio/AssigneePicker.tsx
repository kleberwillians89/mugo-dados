import type { Person } from "../../app/crm";

/**
 * Responsáveis da tarefa, depois do departamento: escolhida a área, aparecem primeiro as pessoas dela (configuradas em
 * Configurações → Usuários). Sem área escolhida, ou sem ninguém configurado nela, a pessoa pode escolher entre todos.
 * Quem já está marcado aparece sempre. Várias pessoas por tarefa.
 */
export default function AssigneePicker({ team, area, all, onAll, selected, onChange, disabled }: {
  team: Person[]; area: string; all: boolean; onAll: () => void; selected: string[]; onChange: (ids: string[]) => void; disabled?: boolean;
}) {
  const fromArea = area ? team.filter((p) => p.departments?.includes(area)) : [];
  const base = all ? team : fromArea;
  const shown = [...base, ...team.filter((p) => selected.includes(p.user_id) && !base.some((b) => b.user_id === p.user_id))];
  const toggle = (id: string, on: boolean) => onChange(on ? [...selected, id] : selected.filter((x) => x !== id));

  return <fieldset className="taskAssigneePicker" disabled={disabled}>
    <legend>Responsáveis <small>({selected.length} selecionado{selected.length === 1 ? "" : "s"})</small></legend>
    {!all && !area ? <p className="libHint">Escolha o departamento para ver quem é da área.</p> : null}
    {!all && area && !fromArea.length ? <p className="libHint">Ninguém com a área {area} configurada ainda (Configurações → Usuários).</p> : null}
    {shown.length ? <div className="taskAssigneeOptions" role="group" aria-label="Selecione um ou mais responsáveis">
      {shown.map((p) => <label key={p.user_id} className={selected.includes(p.user_id) ? "is-selected" : ""}>
        <input type="checkbox" checked={selected.includes(p.user_id)} onChange={(e) => toggle(p.user_id, e.target.checked)} />
        <span>{p.name}</span>
      </label>)}
    </div> : null}
    {!all ? <button type="button" className="ds-link is-quiet" onClick={onAll}>{area && fromArea.length ? "Mostrar pessoas de outras áreas" : "Escolher entre todos"}</button> : null}
  </fieldset>;
}
