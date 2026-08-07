import { useState } from "react";
import type { ClientMembership } from "../app/api";

type Props = {
  clients: ClientMembership[];
  activeClientId: string;
  onChange: (clientId: string) => void;
};

const ROLE_LABELS: Record<string, string> = {
  platform_admin: "Administrador da plataforma",
  agency_admin: "Administrador da agência",
  client_admin: "Administrador do cliente",
  owner: "Responsável",
  viewer: "Somente leitura",
};

export default function ClientSwitcher({ clients, activeClientId, onChange }: Props) {
  const [pendingId, setPendingId] = useState<string | null>(null);
  if (pendingId && pendingId === activeClientId) {
    // Ajuste em tempo de render: assim que o pai confirmar a troca via prop,
    // encerramos o estado "trocando" no mesmo ciclo, sem passar por useEffect.
    setPendingId(null);
  }

  if (!clients.length) return null;
  const activeClient = clients.find((client) => client.client_id === activeClientId);
  const initial = String(activeClient?.name || "M").trim().slice(0, 1).toUpperCase();
  const roleLabel = activeClient?.role ? ROLE_LABELS[activeClient.role] || activeClient.role : null;
  const pendingClient = pendingId ? clients.find((client) => client.client_id === pendingId) : null;

  return (
    <div
      className={`clientSwitcher${pendingClient ? " is-switching" : ""}`}
      title={roleLabel ? `Papel: ${roleLabel}` : undefined}
    >
      <span className="clientSwitcherAvatar" aria-hidden="true">{initial}</span>
      <span className="clientSwitcherLabel">
        {pendingClient ? `Trocando para ${pendingClient.name}…` : "Empresa ativa"}
      </span>
      <select
        aria-label="Selecionar empresa"
        value={activeClientId}
        disabled={Boolean(pendingClient)}
        onChange={(event) => {
          setPendingId(event.target.value);
          onChange(event.target.value);
        }}
      >
        {clients.map((client) => (
          <option key={client.client_id} value={client.client_id}>
            {client.name}
          </option>
        ))}
      </select>
      <span className="clientSwitcherLock" aria-live="polite">
        <i aria-hidden="true" /> {pendingClient ? "Trocando…" : roleLabel || "Ativa"}
      </span>
    </div>
  );
}
