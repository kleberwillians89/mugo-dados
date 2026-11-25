export function shouldOpenHomeAfterSignIn({
  event,
  bootstrapCompleted,
  knownUserId,
  nextUserId,
  requestedRoute,
  hasSetupSignal,
}: {
  event: string;
  bootstrapCompleted: boolean;
  knownUserId: string | null;
  nextUserId: string | null;
  requestedRoute: string;
  hasSetupSignal: boolean;
}): boolean {
  return event === "SIGNED_IN" && bootstrapCompleted && Boolean(nextUserId) && knownUserId !== nextUserId && requestedRoute === "home" && !hasSetupSignal;
}

/** Somente o evento oficial do Supabase acompanhado de sessão válida autoriza a troca de senha. */
export function isValidPasswordRecoveryEvent(event: string, hasSession: boolean): boolean {
  return event === "PASSWORD_RECOVERY" && hasSession;
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
