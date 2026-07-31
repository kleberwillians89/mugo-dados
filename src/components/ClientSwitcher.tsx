import type { ClientMembership } from "../app/api";

type Props = {
  clients: ClientMembership[];
  activeClientId: string;
  onChange: (clientId: string) => void;
};

export default function ClientSwitcher({ clients, activeClientId, onChange }: Props) {
  if (!clients.length) return null;
  const activeClient = clients.find((client) => client.client_id === activeClientId);
  const initial = String(activeClient?.name || "M").trim().slice(0, 1).toUpperCase();
  return (
    <div className="clientSwitcher">
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
      <span className="clientSwitcherLock"><i aria-hidden="true" /> Ativa</span>
    </div>
  );
}
