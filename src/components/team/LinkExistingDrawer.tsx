import { useEffect, useState } from "react";
import Drawer from "../Drawer";
import { linkExistingMember, searchLinkableAccounts, type LinkableAccount } from "../../app/team";

/**
 * Adicionar usuário existente (só equipe Mugô): busca contas que já existem e vincula à empresa atual.
 * Nunca pede senha nem cria outra conta. Equipe Mugô entra como equipe desta empresa (aparece nos responsáveis);
 * conta de cliente entra só com visualização, e as permissões se ajustam depois em "Permissões".
 */
export default function LinkExistingDrawer({ open, clientName, onClose, onLinked }: {
  open: boolean; clientName: string; onClose: () => void; onLinked: (who: LinkableAccount) => void;
}) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<LinkableAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!open) { setQuery(""); setItems(null); setError(null); return undefined; }
    const term = query.trim();
    if (term.length < 2) { setItems(null); return undefined; }
    let alive = true;
    const handle = window.setTimeout(() => {
      searchLinkableAccounts(term).then((out) => { if (alive) { setItems(out.items); setError(null); } })
        .catch((cause) => { if (alive) { setItems(null); setError(cause instanceof Error ? cause.message : "Não foi possível buscar agora."); } });
    }, 300);
    return () => { alive = false; window.clearTimeout(handle); };
  }, [open, query]);

  async function link(account: LinkableAccount) {
    setBusy(account.user_id); setError(null);
    try {
      await linkExistingMember(account.team ? { user_id: account.user_id } : { user_id: account.user_id, preset: "visualizacao", view_all: false, access_total: false });
      onLinked(account);
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível vincular agora.");
    } finally { setBusy(null); }
  }

  return <Drawer open={open} width="md" title="Adicionar usuário existente"
    description={`Para quem já tem conta no Mugoverso. A pessoa entra em ${clientName} com o mesmo login e a mesma senha de sempre.`}
    onClose={() => { if (!busy) onClose(); }}>
    <div className="usersLinkForm">
      <label className="ds-field">Buscar por nome ou e-mail
        <input type="search" autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ex.: liliu" />
      </label>
      {error ? <p className="usersLinkError" role="alert">{error}</p> : null}
      {query.trim().length < 2 ? <p className="usersHint">Digite ao menos 2 letras.</p>
        : items === null ? (error ? null : <p className="usersHint">Buscando…</p>)
        : !items.length ? <p className="usersHint">Ninguém encontrado fora de {clientName}. Para quem ainda não tem conta, use "+ Novo usuário".</p>
        : <ul className="usersLinkList">{items.map((a) => <li key={a.user_id}>
            <span><b>{a.name || a.login}</b><small>{a.login}{a.team ? " · Equipe Mugô" : " · Cliente"}</small></span>
            <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void link(a)}>
              {busy === a.user_id ? "Vinculando…" : "Vincular"}</button>
          </li>)}</ul>}
      <p className="usersHint">Vincular não muda a senha, não cria outra conta e não mexe nos acessos da pessoa em outras empresas.</p>
    </div>
  </Drawer>;
}
