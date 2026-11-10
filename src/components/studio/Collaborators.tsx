import { useState } from "react";
import { X } from "lucide-react";
import { cleanHandle } from "./collaborators.helpers";


/**
 * Colaboradores do post no Instagram (até 3). O convite aparece para cada @ no Instagram dele;
 * quando ele aceita, o post fica no perfil dos dois. Stories não aceitam colaborador.
 */
export default function Collaborators({ value, onChange, disabled, isStory }: { value: string[]; onChange: (next: string[]) => void; disabled?: boolean; isStory?: boolean }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  function add() {
    const handles = text.split(/[\s,;]+/).filter(Boolean);
    if (!handles.length) return;
    const next = [...value];
    for (const raw of handles) {
      const user = cleanHandle(raw);
      if (!user) { setError(`“${raw}” não é um @ válido do Instagram.`); return; }
      if (!next.includes(user)) next.push(user);
    }
    if (next.length > 3) { setError("O Instagram aceita no máximo 3 colaboradores por post."); return; }
    setError(null); setText(""); onChange(next);
  }
  return <div className="collab">
    <span className="postArtTitle">Colaboradores <em className="is-muted">até 3 @</em></span>
    {value.length ? <ul className="collabChips">{value.map((u) => <li key={u}>@{u}
      <button type="button" aria-label={`Tirar @${u}`} disabled={disabled} onClick={() => onChange(value.filter((x) => x !== u))}><X size={12} /></button></li>)}</ul> : null}
    {value.length < 3 ? <div className="postArtFromLink">
      <input value={text} placeholder="@perfil do colaborador" aria-label="@ do colaborador" disabled={disabled}
        onChange={(e) => { setText(e.target.value); setError(null); }} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
      <button type="button" className="ds-button" disabled={disabled || !text.trim()} onClick={add}>Marcar</button>
    </div> : null}
    {error ? <small className="studioError">{error}</small> : null}
    {isStory && value.length ? <small className="postArtHint is-pending">Stories não aceitam colaborador: o Instagram publica sem a marcação.</small>
      : <small className="libHint">Cada @ recebe um convite no Instagram. Quando aceita, o post aparece no perfil dos dois.</small>}
  </div>;
}
