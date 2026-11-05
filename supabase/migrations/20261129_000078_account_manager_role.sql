-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Papel "gestora da conta" (account_manager): equipe Mugô só na empresa onde tem o papel
-- (cria calendário, gera com IA, envia para aprovação). Não vê outras empresas.
alter table public.client_memberships drop constraint if exists client_memberships_role_check;
alter table public.client_memberships add constraint client_memberships_role_check
  check (role in ('owner', 'agency_admin', 'account_manager', 'client_admin', 'viewer'));

alter table public.user_invitations drop constraint if exists user_invitations_role_check;
alter table public.user_invitations add constraint user_invitations_role_check
  check (role in ('owner', 'agency_admin', 'account_manager', 'client_admin', 'viewer'));

notify pgrst, 'reload schema';
