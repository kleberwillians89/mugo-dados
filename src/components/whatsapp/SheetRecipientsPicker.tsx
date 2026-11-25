import { useEffect, useState } from "react";
import { listSheetContacts, type WaSheetContact } from "../../app/whatsapp";

/** Planilha importada: mandar para todos ou escolher à mão (ex.: testar com 2 ou 3 antes de mandar para a base). */
export default function SheetRecipientsPicker({ picked, onChange }: { picked: string[] | null; onChange: (picked: string[] | null) => void }) {
  const manual = picked !== null;
  const [q, setQ] = useState("");
  const [contacts, setContacts] = useState<WaSheetContact[]>([]);
  const [info, setInfo] = useState({ total: 0, matches: 0 });
  const [error, setError] = useState("");

  useEffect(() => {
    if (!manual) return;
    let alive = true;
    const timer = window.setTimeout(() => {
      listSheetContacts(q.trim())
        .then((r) => { if (alive) { setContacts(r.contacts); setInfo({ total: r.total, matches: r.matches }); setError(""); } })
        .catch((e) => { if (alive) setError(e instanceof Error ? e.message : "Não consegui carregar a planilha."); });
    }, 250);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [manual, q]);

  const chosen = new Set(picked || []);
  const toggle = (id: string) => onChange(chosen.has(id) ? [...chosen].filter((x) => x !== id) : [...chosen, id]);

  return <fieldset className="waBulkPick">
    <legend>Quem recebe</legend>
    <label className="waBulkCheck"><input type="radio" name="waPick" checked={!manual} onChange={() => onChange(null)} /> Todos da planilha</label>
    <label className="waBulkCheck"><input type="radio" name="waPick" checked={manual} onChange={() => onChange([])} /> Escolher contatos (bom para testar antes)</label>
    {manual ? <div className="waBulkPickList">
      <input type="search" placeholder="Buscar por nome ou final do número" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar contato" />
      <small>{chosen.size} escolhido(s){info.total ? ` de ${info.total}` : ""}{q && info.matches > contacts.length ? ` · mostrando ${contacts.length} de ${info.matches}` : ""}</small>
      {error ? <p className="waBulkError" role="alert">{error}</p> : null}
      <ul>{contacts.map((c) => <li key={c.id}><label className="waBulkCheck">
        <input type="checkbox" checked={chosen.has(c.id)} onChange={() => toggle(c.id)} /> <span>{c.name}</span> <small>{c.phone}</small>
      </label></li>)}</ul>
      {!contacts.length && !error ? <small>Nenhum contato encontrado.</small> : null}
    </div> : null}
  </fieldset>;
}
