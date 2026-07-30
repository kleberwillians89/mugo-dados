import type { ClientMembership } from "../app/api";

type Props = {
  clients: ClientMembership[];
  activeClientId: string;
  onChange: (clientId: string) => void;
};

export default function ClientSwitcher({ clients, activeClientId, onChange }: Props) {
  if (!clients.length) return null;
  return (
    <div className="clientSwitcher">
      <span className="clientSwitcherLabel">Empresa</span>
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
      <span className="clientSwitcherLock">Ambiente isolado</span>
    </div>
  );
}
