import { useRef, useState } from "react";
import type { ClientMembership } from "../app/api";
import { ROLE_LABELS } from "../app/roles";
import { ClientLogo } from "./BrandLogo";

type Props = {
  clients: ClientMembership[];
  activeClientId: string;
  onChange: (clientId: string) => void;
};

export default function ClientSwitcher({ clients, activeClientId, onChange }: Props) {
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);

  if (pendingId && pendingId === activeClientId) {
    // Ajuste em tempo de render: assim que o pai confirmar a troca via prop,
    // encerramos o estado "trocando" no mesmo ciclo, sem passar por useEffect.
    setPendingId(null);
  }

  if (!clients.length) return null;
  const activeClient = clients.find((client) => client.client_id === activeClientId);
  const roleLabel = activeClient?.role ? ROLE_LABELS[activeClient.role] || activeClient.role : null;
  const pendingClient = pendingId ? clients.find((client) => client.client_id === pendingId) : null;
  const isSingleTenant = clients.length === 1;

  const needle = query.trim().toLowerCase();
  const filtered = needle
    ? clients.filter((client) => client.name.toLowerCase().includes(needle))
    : clients;

  function select(clientId: string) {
    setPendingId(clientId);
    onChange(clientId);
    setOpen(false);
    setQuery("");
  }

  function closeOnBlur() {
    window.setTimeout(() => {
      if (rootRef.current && !rootRef.current.contains(document.activeElement)) {
        setOpen(false);
        setQuery("");
      }
    }, 100);
  }

  if (isSingleTenant) {
    return (
      <div className="clientSwitcher clientSwitcherStatic" aria-label={`Empresa ativa: ${activeClient?.name || "Empresa"}`}>
        <div className="clientSwitcherTrigger">
          <ClientLogo clientId={activeClientId} displayName={activeClient?.name} size={32} className="clientSwitcherAvatar" />
          <span className="clientSwitcherIdentity">
            <span className="clientSwitcherName">{activeClient?.name || "Empresa"}</span>
            <span className="clientSwitcherLabel">Empresa ativa{roleLabel ? ` · ${roleLabel}` : ""}</span>
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={rootRef}
      className={`clientSwitcher${pendingClient ? " is-switching" : ""}${open ? " is-open" : ""}`}
      onBlur={closeOnBlur}
    >
      <button
        type="button"
        className="clientSwitcherTrigger"
        aria-label="Selecionar empresa"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={Boolean(pendingClient)}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <ClientLogo clientId={activeClientId} displayName={activeClient?.name} size={32} className="clientSwitcherAvatar" />
        <span className="clientSwitcherIdentity">
          <span className="clientSwitcherName">
            {pendingClient ? `Trocando para ${pendingClient.name}…` : activeClient?.name || "Empresa"}
          </span>
          <span className="clientSwitcherLabel" aria-live="polite">
            {pendingClient ? "Trocando…" : "Empresa ativa"}
            {!pendingClient && roleLabel ? ` · ${roleLabel}` : ""}
          </span>
        </span>
        <svg className="clientSwitcherChevron" width="10" height="6" viewBox="0 0 10 6" aria-hidden="true">
          <path d="M1 1L5 5L9 1" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open ? (
        <div className="clientSwitcherPanel" role="listbox" aria-label="Empresas disponíveis">
          {clients.length > 4 ? (
            <input
              type="search"
              className="clientSwitcherSearch"
              placeholder="Buscar empresa"
              value={query}
              autoFocus
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setOpen(false);
                if (event.key === "Enter" && filtered[0]) select(filtered[0].client_id);
              }}
            />
          ) : null}
          <div className="clientSwitcherList">
            {filtered.length === 0 ? (
              <div className="clientSwitcherEmpty">Nenhuma empresa encontrada.</div>
            ) : (
              filtered.map((client) => (
                <button
                  type="button"
                  key={client.client_id}
                  className={`clientSwitcherOption${client.client_id === activeClientId ? " is-selected" : ""}`}
                  role="option"
                  aria-selected={client.client_id === activeClientId}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    select(client.client_id);
                  }}
                >
                  <ClientLogo clientId={client.client_id} displayName={client.name} size={32} />
                  <span className="clientSwitcherOptionName">{client.name}</span>
                  <span className="clientSwitcherOptionStatus">
                    {client.client_id === activeClientId
                      ? "Ativa"
                      : (client.role ? ROLE_LABELS[client.role] : null) || client.role || "Convidado"}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
