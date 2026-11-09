-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Usuários e acessos por módulo (modelo do CRM Ruah), por empresa.
-- client_memberships ganha status, preset e as chaves "ver tudo"/"acesso total"; os ajustes finos
-- (código concedido ou retirado em relação ao preset) ficam em client_member_permissions.
-- Membros existentes recebem o equivalente ao papel atual: client_admin/owner/admin = Administrador
-- (acesso total); viewer = Visualização (ver tudo). Equipe Mugô não usa estas colunas.

alter table public.client_memberships add column if not exists status text not null default 'active';
alter table public.client_memberships add column if not exists permission_preset text;
alter table public.client_memberships add column if not exists view_all boolean not null default false;
alter table public.client_memberships add column if not exists access_total boolean not null default false;
alter table public.client_memberships add column if not exists username text;
alter table public.client_memberships add column if not exists updated_at timestamptz not null default now();

alter table public.client_memberships drop constraint if exists client_memberships_status_check;
alter table public.client_memberships add constraint client_memberships_status_check
  check (status in ('active', 'inactive'));
alter table public.client_memberships drop constraint if exists client_memberships_preset_check;
alter table public.client_memberships add constraint client_memberships_preset_check
  check (permission_preset is null or permission_preset in
    ('administrador', 'gestor', 'marketing', 'comercial', 'visualizacao', 'personalizado'));

update public.client_memberships
   set permission_preset = 'administrador', view_all = true, access_total = true
 where permission_preset is null and role in ('client_admin', 'owner', 'admin');
update public.client_memberships
   set permission_preset = 'visualizacao', view_all = true, access_total = false
 where permission_preset is null and role = 'viewer';

create table if not exists public.client_member_permissions (
  client_id text not null references public.clients(id) on delete cascade,
  user_id uuid not null,
  permission_code text not null check (permission_code ~ '^[a-z_]+\.(view|edit)$'),
  granted boolean not null,
  created_at timestamptz not null default now(),
  primary key (client_id, user_id, permission_code)
);
create index if not exists client_member_permissions_member_idx on public.client_member_permissions (client_id, user_id);

alter table public.client_member_permissions enable row level security;
revoke all on public.client_member_permissions from anon, authenticated;
grant select on public.client_member_permissions to authenticated;
grant all on public.client_member_permissions to service_role;
drop policy if exists client_member_permissions_self_read on public.client_member_permissions;
create policy client_member_permissions_self_read on public.client_member_permissions
  for select to authenticated using (user_id = auth.uid());

notify pgrst, 'reload schema';
