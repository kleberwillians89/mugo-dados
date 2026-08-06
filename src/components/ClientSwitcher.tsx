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
  if (!clients.length) return null;
  const activeClient = clients.find((client) => client.client_id === activeClientId);
  const initial = String(activeClient?.name || "M").trim().slice(0, 1).toUpperCase();
  const roleLabel = activeClient?.role ? ROLE_LABELS[activeClient.role] || activeClient.role : null;
  return (
    <div className="clientSwitcher" title={roleLabel ? `Papel: ${roleLabel}` : undefined}>
      <span className="clientSwitcherAvatar" aria-hidden="true">{initial}</span>
      <span className="clientSwitcherLabel">Empresa ativa</span>
      <select
        aria-label="Selecionar empresa"
        value={activeClientId}
        onChange={(event) => onChange(event.target.value)}
      >
        {clients.map((client) => (
          <option key={client.client_id} value={client.client_id}>
            {client.name}
          </option>
        ))}
      </select>
      <span className="clientSwitcherLock"><i aria-hidden="true" /> {roleLabel || "Ativa"}</span>
    </div>
  );
}
