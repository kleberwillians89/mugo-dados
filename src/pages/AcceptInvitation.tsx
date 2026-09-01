import { useState } from "react";
import { ApiError, acceptInvitation, type PendingInvitation } from "../app/api";
import MugoLogo from "../components/MugoLogo";
import "../components/mugo-logo.css";

type Props = {
  invitations: PendingInvitation[];
  onAccepted: (accepted?: { clientId: string | null; role: string | null }) => Promise<void> | void;
  onSkip: () => void;
  onLogout: () => void | Promise<void>;
};

const ROLE_LABEL: Record<string, string> = {
  owner: "Responsável",
  agency_admin: "Administrador da agência",
  client_admin: "Administrador da empresa",
  viewer: "Somente leitura",
};

export default function AcceptInvitation({ invitations, onAccepted, onSkip, onLogout }: Props) {
  const [pending, setPending] = useState<PendingInvitation[]>(invitations);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function accept(invitation: PendingInvitation) {
    setBusyId(invitation.id);
    setError(null);
    try {
      // O tenant/role de destino vêm da resposta do backend (RPC
      // accept_user_invitation), que deriva os valores da própria invitation —
      // nunca de um client_id escolhido no frontend.
      const result = await acceptInvitation(invitation.id);
      const remaining = pending.filter((item) => item.id !== invitation.id);
      setPending(remaining);
      if (remaining.length === 0) {
        await onAccepted({ clientId: result.client_id, role: result.role });
      }
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? `${cause.message}${cause.code ? ` Código: ${cause.code}.` : ""}`
          : cause instanceof Error
            ? cause.message
            : "Não foi possível aceitar o convite."
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="companiesPage" aria-labelledby="acceptInvitationTitle">
      <header className="companiesHeader">
        <div>
          <MugoLogo variant="symbol" className="appBootMark" alt="" />
          <span className="companiesEyebrow">Convite de acesso</span>
          <h1 id="acceptInvitationTitle">Você foi convidado para uma empresa</h1>
          <p>Confirme o convite para acessar os dados. Suas outras empresas continuam disponíveis.</p>
        </div>
        <div className="companiesActions">
          <button type="button" className="btn" onClick={() => void onLogout()}>Sair</button>
        </div>
      </header>

      {error ? <p className="companiesError" role="alert">{error}</p> : null}

      <section className="companiesCard">
        {pending.length === 0 ? (
          <p className="companiesEmptyState">Nenhum convite pendente.</p>
        ) : (
          <div className="companiesTableWrap">
            <table className="companiesTable">
              <thead><tr><th>Empresa</th><th>Papel</th><th /></tr></thead>
              <tbody>
                {pending.map((invitation) => (
                  <tr key={invitation.id}>
                    <td><strong>{invitation.company_name}</strong></td>
                    <td>{ROLE_LABEL[invitation.role] || invitation.role}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btnPrimary"
                        disabled={busyId === invitation.id}
                        onClick={() => void accept(invitation)}
                      >
                        {busyId === invitation.id ? "Aceitando..." : "Aceitar convite"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="companiesRowActions">
        <button type="button" className="btn" onClick={onSkip}>
          {pending.length === 0 ? "Continuar" : "Pular por agora"}
        </button>
      </div>
    </main>
  );
}
