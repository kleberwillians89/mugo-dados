// HARNESS DE REVISÃO VISUAL — somente desenvolvimento (fora do build).
// Tela real de aceite de convite (AcceptInvitation) com convites de exemplo.
// O aceite passa pelo mock de /api/invitations/{id}/accept em main.tsx.

import type { PendingInvitation } from "../app/api";
import AcceptInvitation from "../pages/AcceptInvitation";

const inDays = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString();

const ORIGAMI: PendingInvitation = {
  id: "convite-origami", client_id: "origami", role: "client_admin", company_name: "Origami", expires_at: inDays(10),
};
const ROOVE: PendingInvitation = {
  id: "convite-roove", client_id: "roove", role: "viewer", company_name: "Roove", expires_at: inDays(14),
};
// Backend sem nome da empresa: devolve "Empresa" (fallback de list_pending_invitations_for_email).
const SEM_NOME: PendingInvitation = {
  id: "convite-sem-nome", client_id: "c-9f2", role: "viewer", company_name: "Empresa", expires_at: inDays(7),
};

function invitationsFor(state: string): PendingInvitation[] {
  if (state === "varias") return [ORIGAMI, ROOVE];
  if (state === "sem-nome") return [SEM_NOME];
  return [ORIGAMI];
}

export default function ReviewInvite({ state }: { state: string }) {
  const destination = `${window.location.pathname}?tela=ecommerce&perfil=cliente&${state === "varias" ? "empresas=2" : "empresa=origami"}`;
  return (
    <AcceptInvitation
      invitations={invitationsFor(state)}
      onAccepted={() =>
        state === "sucesso"
          // Fica em "Abrindo…" para revisão do estado de redirecionamento.
          ? new Promise<void>(() => undefined)
          : new Promise<void>((resolve) => {
              window.setTimeout(() => {
                window.location.assign(destination);
                resolve();
              }, 1500);
            })
      }
      onSkip={() => window.location.assign(destination)}
      onLogout={() => window.location.assign(`${window.location.pathname}?tela=login`)}
    />
  );
}
