import { useState } from "react";
import Drawer from "../Drawer";
import { setMemberDepartments, type TeamMember } from "../../app/team";

/** Áreas de um integrante: chips na tabela de Usuários e um modal para marcar (uma pessoa pode ter várias). */
export function DepartmentChips({ areas }: { areas: string[] }) {
  if (!areas.length) return <small className="usersMuted">Sem área</small>;
  return <span className="usersAreas">{areas.map((a) => <span key={a} className="usersArea">{a}</span>)}</span>;
}

export default function MemberDepartmentsEditor({ member, catalog, current, onClose, onSaved }: {
  member: TeamMember; catalog: string[]; current: string[]; onClose: () => void; onSaved: (areas: string[]) => void;
}) {
  const [picked, setPicked] = useState<string[]>(current);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = (area: string) => setPicked((list) => (list.includes(area) ? list.filter((a) => a !== area) : [...list, area]));

  async function save() {
    setBusy(true); setError(null);
    try { onSaved((await setMemberDepartments(member.user_id, picked)).departments); }
    catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível salvar as áreas."); }
    finally { setBusy(false); }
  }

  return <Drawer open title={`Áreas de ${member.name || member.login}`} onClose={() => { if (!busy) onClose(); }}
    description="Na Nova tarefa, ao escolher a área, essas pessoas aparecem primeiro como responsáveis. Vale em todos os clientes.">
    <div className="usersAreasForm">
      {catalog.map((area) => <label key={area} className="usersCheck">
        <input type="checkbox" checked={picked.includes(area)} onChange={() => toggle(area)} /> {area}</label>)}
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      <div className="usersFormActions">
        <button type="button" className="ds-button" onClick={onClose} disabled={busy}>Cancelar</button>
        <button type="button" className="ds-button is-primary" onClick={() => void save()} disabled={busy}>{busy ? "Salvando…" : "Salvar áreas"}</button>
      </div>
    </div>
  </Drawer>;
}
