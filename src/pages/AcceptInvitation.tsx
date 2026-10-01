import { useState } from "react";
import { ApiError, acceptInvitation, type PendingInvitation } from "../app/api";
import { ACCOUNT_ROLE_LABELS } from "../app/roles";
import AuthFrame from "../components/auth/AuthFrame";
import ClientBrand from "../components/ClientBrand";

type Props = {
  invitations: PendingInvitation[];
  onAccepted: (accepted?: { clientId: string | null; role: string | null }) => Promise<void> | void;
  onSkip: () => void;
  onLogout: () => void | Promise<void>;
};

type AcceptedInvitation = { clientId: string; companyName: string | null };
type AcceptFailure = { title: string; message: string; code: string | null };

/**
 * Nome real da empresa convidante. "Empresa" e o próprio id são o fallback do
 * backend (list_pending_invitations_for_email) quando o nome não existe: não
 * viram marca nem nome na tela.
 */
function companyNameOf(invitation: PendingInvitation): string | null {
  const name = String(invitation.company_name || "").trim();
  if (!name || name === "Empresa" || name === invitation.client_id) return null;
  return name;
}

function formatDeadline(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric", timeZone: "America/Sao_Paulo",
  });
}

/**
 * Título do estado a partir do que o backend já devolve (status HTTP da rota
 * de aceite). A mensagem exibida continua sendo a do backend.
 */
function describeFailure(cause: unknown): AcceptFailure {
  if (cause instanceof ApiError) {
    const title =
      cause.status === 404 ? "Convite inválido"
        : cause.status === 409 && /expir/i.test(cause.message) ? "Convite expirado"
          : cause.status === 409 ? "Convite indisponível"
            : cause.status === 403 ? "Convite de outra conta"
              : cause.status === 401 ? "Sessão expirada"
                : "Não foi possível aceitar o convite";
    return { title, message: cause.message, code: cause.code || null };
  }
  return {
    title: "Não foi possível aceitar o convite",
    message: cause instanceof Error && cause.message ? cause.message : "Não foi possível aceitar o convite.",
    code: null,
  };
}

function InviteDetails({ invitation }: { invitation: PendingInvitation }) {
  const deadline = formatDeadline(invitation.expires_at);
  return (
    <dl className="inviteDetails">
      <div>
        <dt>Perfil</dt>
        <dd>{ACCOUNT_ROLE_LABELS[invitation.role] || invitation.role}</dd>
      </div>
      {deadline ? (
        <div>
          <dt>Válido até</dt>
          <dd>{deadline}</dd>
        </div>
      ) : null}
    </dl>
  );
}

/** Aceite de convite: mesma moldura do acesso, empresa em destaque quando o nome existe. */
export default function AcceptInvitation({ invitations, onAccepted, onSkip, onLogout }: Props) {
  const [pending, setPending] = useState<PendingInvitation[]>(invitations);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<AcceptFailure | null>(null);
  const [accepted, setAccepted] = useState<AcceptedInvitation | null>(null);

  async function accept(invitation: PendingInvitation) {
    setBusyId(invitation.id);
    setError(null);
    try {
      // O tenant/role de destino vêm da resposta do backend (RPC
      // accept_user_invitation), que deriva os valores da própria invitation —
      // nunca de um client_id escolhido no frontend.
      const result = await acceptInvitation(invitation.id);
      const remaining = pending.filter((item) => item.id !== invitation.id);
      setAccepted({ clientId: invitation.client_id, companyName: companyNameOf(invitation) });
      setPending(remaining);
      if (remaining.length === 0) {
        await onAccepted({ clientId: result.client_id, role: result.role });
      }
    } catch (cause) {
      setError(describeFailure(cause));
    } finally {
      setBusyId(null);
    }
  }

  const single = pending.length === 1 ? pending[0] : null;
  const singleName = single ? companyNameOf(single) : null;
  // Último convite aceito e o App já abrindo a empresa (onAccepted em andamento).
  const opening = pending.length === 0 && accepted !== null && busyId !== null;

  return (
    <AuthFrame labelledBy="invite-title">
      <p className="authEyebrow">Convite de acesso</p>

      {pending.length === 0 ? (
        accepted ? (
          <>
            <h1 id="invite-title" className="loginTitle">Convite aceito</h1>
            {accepted.companyName ? (
              <ClientBrand clientId={accepted.clientId} clientName={accepted.companyName} titleAs="p" className="inviteCompany" />
            ) : null}
            <p className="loginMessage" role="status">
              {opening ? `Abrindo ${accepted.companyName || "a empresa"}…` : "Seu acesso está pronto."}
            </p>
          </>
        ) : (
          <>
            <h1 id="invite-title" className="loginTitle">Nenhum convite pendente</h1>
            <p className="loginLead">Não há convites aguardando resposta nesta conta.</p>
          </>
        )
      ) : single ? (
        <>
          <h1 id="invite-title" className="inviteTitle">
            {singleName ? (
              <>
                <span className="inviteTitleLead">Você foi convidado para</span>
                <ClientBrand clientId={single.client_id} clientName={singleName} titleAs="span" inline className="inviteCompany" />
              </>
            ) : (
              "Você foi convidado para uma empresa"
            )}
          </h1>
          <InviteDetails invitation={single} />
          <p className="loginLead">Ao aceitar, a empresa passa a aparecer na sua conta do Mugô Dados.</p>
        </>
      ) : (
        <>
          <h1 id="invite-title" className="loginTitle">Você foi convidado para {pending.length} empresas</h1>
          <p className="loginLead">Aceite cada convite para a empresa aparecer na sua conta do Mugô Dados.</p>
        </>
      )}

      {accepted && pending.length > 0 ? (
        <p className="loginMessage" role="status">Convite para {accepted.companyName || "a empresa"} aceito.</p>
      ) : null}

      {error ? (
        <div className="loginMessage is-error inviteError" role="alert">
          <strong>{error.title}</strong>
          <span>{error.message}</span>
          {error.code ? <small>Código para o suporte: {error.code}</small> : null}
        </div>
      ) : null}

      {single ? (
        <button
          type="button"
          className="loginSubmit inviteAccept"
          disabled={busyId === single.id}
          aria-busy={busyId === single.id}
          onClick={() => void accept(single)}
        >
          {busyId === single.id ? "Aceitando..." : "Aceitar convite"}
        </button>
      ) : pending.length > 1 ? (
        <ul className="inviteList">
          {pending.map((invitation) => {
            const name = companyNameOf(invitation);
            const busy = busyId === invitation.id;
            return (
              <li key={invitation.id} className="inviteItem">
                {name ? (
                  <ClientBrand clientId={invitation.client_id} clientName={name} titleAs="p" size="compact" className="inviteItemBrand" />
                ) : (
                  <p className="inviteItemName">Empresa sem nome informado</p>
                )}
                <InviteDetails invitation={invitation} />
                <button
                  type="button"
                  className="inviteItemAccept"
                  disabled={busy}
                  aria-busy={busy}
                  aria-label={`Aceitar convite para ${name || "a empresa"}`}
                  onClick={() => void accept(invitation)}
                >
                  {busy ? "Aceitando..." : "Aceitar convite"}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {pending.length === 0 && !opening ? (
        <button type="button" className="loginSubmit" onClick={onSkip}>Continuar</button>
      ) : null}
      <div className="loginSecondary">
        {pending.length > 0 ? (
          <button type="button" className="loginTextButton" onClick={onSkip}>Pular por agora</button>
        ) : null}
        <button type="button" className="loginTextButton" onClick={() => void onLogout()}>Sair</button>
      </div>
    </AuthFrame>
  );
}
