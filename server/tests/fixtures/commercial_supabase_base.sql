-- Synthetic prerequisites exclusively for the disposable Supabase CLI stack.
-- This file is NOT an application migration and must never run on hosted projects.
create table public.clients (
  id text primary key,
  name text not null,
  created_at timestamptz not null default now()
);
create table public.client_memberships (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id),
  client_id text not null references public.clients(id),
  role text not null,
  created_at timestamptz not null default now(),
  unique (user_id,client_id)
);
create table public.platform_admins (
  user_id uuid primary key references auth.users(id),
  role text not null check (role='platform_admin'),
  granted_at timestamptz not null default now()
);
alter table public.clients enable row level security;
alter table public.client_memberships enable row level security;
alter table public.platform_admins enable row level security;
revoke all on public.clients, public.client_memberships, public.platform_admins from anon, authenticated;
grant all on public.clients, public.client_memberships, public.platform_admins to service_role;

create or replace function public.is_platform_admin(p_user_id uuid default auth.uid())
returns boolean language sql stable security definer set search_path = public
as $$
  select exists(select 1 from public.platform_admins
    where user_id = p_user_id and role = 'platform_admin');
$$;
revoke all on function public.is_platform_admin(uuid) from public, anon;
grant execute on function public.is_platform_admin(uuid) to authenticated, service_role;
