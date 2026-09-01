export function shouldOpenMetaAfterSignIn({
  event,
  bootstrapCompleted,
  knownUserId,
  nextUserId,
}: {
  event: string;
  bootstrapCompleted: boolean;
  knownUserId: string | null;
  nextUserId: string | null;
}): boolean {
  return event === "SIGNED_IN" && bootstrapCompleted && Boolean(nextUserId) && knownUserId !== nextUserId;
}

// Papéis que administram integrações da empresa (mesma lista usada pelo guard
// de rota e por Onboarding.tsx). viewer e qualquer papel desconhecido caem
// fora — nunca ganham acesso de mutação por este caminho.
const INTEGRATION_MANAGER_ROLES = new Set([
  "platform_admin",
  "agency_admin",
  "client_admin",
  "owner",
  "admin",
]);

export function canManageIntegrationsRole(role: string | null | undefined): boolean {
  return INTEGRATION_MANAGER_ROLES.has(String(role || "").trim().toLowerCase());
}

/**
 * Rota de destino depois que um usuário entra pelo onboarding (link de
 * ativação ou aceitação explícita de invitation). Quem pode gerenciar
 * integrações cai direto em "Integrações"; viewer segue para o dashboard,
 * exatamente como o guard de rota já faz hoje.
 */
export function routeAfterInvitationAccepted(
  role: string | null | undefined
): "integrations" | "meta" {
  return canManageIntegrationsRole(role) ? "integrations" : "meta";
}
