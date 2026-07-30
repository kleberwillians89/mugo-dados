-- Multi-tenant foundation (compatível com base antiga)
-- Objetivo: não apagar cliente antigo, não quebrar ids text já existentes,
-- e migrar client_users + clients.ig_access_token para o novo modelo.

create extension if not exists pgcrypto;

-- clients (se não existir)
create table if not exists public.clients (
  id text primary key default gen_random_uuid()::text,
  name text not null,
  ig_user_id text,
  created_at timestamptz not null default now()
);

alter table public.clients add column if not exists ig_user_id text;
alter table public.clients add column if not exists created_at timestamptz default now();

-- memberships (client_id em TEXT para compatibilidade com legado)
create table if not exists public.client_memberships (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  client_id text not null,
  role text not null check (role in ('owner', 'admin', 'viewer')),
  created_at timestamptz not null default now(),
  unique(user_id, client_id)
);
create index if not exists idx_client_memberships_user on public.client_memberships(user_id);
create index if not exists idx_client_memberships_client on public.client_memberships(client_id);

-- Meta connection por cliente
create table if not exists public.meta_connections (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  platform text not null check (platform in ('instagram')),
  access_token text not null,
  expires_at timestamptz,
  last_refresh_at timestamptz,
  status text not null default 'active' check (status in ('active','needs_reauth','error')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, platform)
);
create index if not exists idx_meta_connections_status on public.meta_connections(status);
create index if not exists idx_meta_connections_expires_at on public.meta_connections(expires_at);

-- auditoria de tokens
create table if not exists public.meta_token_events (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  event_type text not null,
  ok boolean not null,
  details_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_meta_token_events_client_created on public.meta_token_events(client_id, created_at desc);

-- notas por cliente
create table if not exists public.client_notes (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  title text not null default 'Sem título',
  body text not null default '',
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create index if not exists idx_client_notes_client_updated on public.client_notes(client_id, updated_at desc);

-- comentários IG
create table if not exists public.ig_comments (
  id bigserial primary key,
  client_id text not null,
  media_id text not null,
  comment_id text not null,
  text text,
  username text,
  timestamp timestamptz,
  created_at timestamptz not null default now(),
  unique(client_id, comment_id)
);
create index if not exists idx_ig_comments_client_ts on public.ig_comments(client_id, timestamp desc);
create index if not exists idx_ig_comments_media on public.ig_comments(client_id, media_id);

-- mídia IG persistida
create table if not exists public.ig_media (
  id bigserial primary key,
  client_id text not null,
  media_id text not null,
  media_type text,
  media_product_type text,
  caption text,
  permalink text,
  timestamp timestamptz,
  thumb_url text,
  insights_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, media_id)
);
create index if not exists idx_ig_media_client_ts on public.ig_media(client_id, timestamp desc);

-- snapshots: garante índice tenant/date
create index if not exists idx_ig_profile_snapshots_client_date
  on public.ig_profile_snapshots(client_id, snapshot_date desc);

-- locks para cron/idempotência
create table if not exists public.cron_locks (
  id bigserial primary key,
  client_id text not null,
  job_name text not null,
  locked_until timestamptz not null,
  updated_at timestamptz not null default now(),
  unique(client_id, job_name)
);

-- updated_at trigger helper
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_meta_connections_updated_at on public.meta_connections;
create trigger trg_meta_connections_updated_at
before update on public.meta_connections
for each row execute function public.set_updated_at();

drop trigger if exists trg_client_notes_updated_at on public.client_notes;
create trigger trg_client_notes_updated_at
before update on public.client_notes
for each row execute function public.set_updated_at();

drop trigger if exists trg_ig_media_updated_at on public.ig_media;
create trigger trg_ig_media_updated_at
before update on public.ig_media
for each row execute function public.set_updated_at();

-- lock functions
create or replace function public.acquire_client_job_lock(
  p_client_id text,
  p_job_name text,
  p_ttl_seconds integer default 1200
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_now timestamptz := now();
  v_until timestamptz := now() + make_interval(secs => greatest(30, p_ttl_seconds));
begin
  insert into public.cron_locks(client_id, job_name, locked_until, updated_at)
  values (p_client_id, p_job_name, v_until, v_now)
  on conflict (client_id, job_name)
  do update
    set locked_until = excluded.locked_until,
        updated_at = excluded.updated_at
    where public.cron_locks.locked_until < v_now;

  return exists (
    select 1
    from public.cron_locks l
    where l.client_id = p_client_id
      and l.job_name = p_job_name
      and l.locked_until >= v_now
      and l.updated_at = v_now
  );
end;
$$;

create or replace function public.release_client_job_lock(
  p_client_id text,
  p_job_name text
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.cron_locks
  set locked_until = now() - interval '1 second',
      updated_at = now()
  where client_id = p_client_id
    and job_name = p_job_name;
  return true;
end;
$$;

-- migração do legado: client_users -> client_memberships
-- espera colunas: user_id, client_id
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'client_users'
  ) THEN
    INSERT INTO public.client_memberships (user_id, client_id, role)
    SELECT DISTINCT cu.user_id, cu.client_id::text, 'owner'
    FROM public.client_users cu
    WHERE cu.user_id IS NOT NULL
      AND cu.client_id IS NOT NULL
    ON CONFLICT (user_id, client_id) DO NOTHING;
  END IF;
END $$;

-- migração do legado: clients.ig_access_token -> meta_connections
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema='public' AND table_name='clients' AND column_name='ig_access_token'
  ) THEN
    INSERT INTO public.meta_connections (client_id, platform, access_token, status, last_refresh_at)
    SELECT c.id::text, 'instagram', c.ig_access_token, 'active', now()
    FROM public.clients c
    WHERE coalesce(c.ig_access_token, '') <> ''
    ON CONFLICT (client_id, platform) DO NOTHING;
  END IF;
END $$;

-- RLS helpers
-- Overloads para suportar bases antigas (client_id text) e novas (uuid).
create or replace function public.is_client_member(p_client_id text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.client_memberships m
    where m.client_id = p_client_id
      and m.user_id = auth.uid()
  );
$$;

create or replace function public.is_client_member(p_client_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.client_memberships m
    where m.client_id = p_client_id::text
      and m.user_id = auth.uid()
  );
$$;

alter table public.clients enable row level security;
alter table public.client_memberships enable row level security;
alter table public.client_notes enable row level security;
alter table public.ig_comments enable row level security;
alter table public.ig_media enable row level security;
alter table public.ig_profile_snapshots enable row level security;

-- clients
 drop policy if exists clients_select_member on public.clients;
create policy clients_select_member on public.clients
for select using (public.is_client_member(id::text));

-- memberships
 drop policy if exists memberships_select_own on public.client_memberships;
create policy memberships_select_own on public.client_memberships
for select using (user_id = auth.uid());

-- notes
 drop policy if exists notes_member_select on public.client_notes;
create policy notes_member_select on public.client_notes
for select using (public.is_client_member(client_id));
 drop policy if exists notes_member_insert on public.client_notes;
create policy notes_member_insert on public.client_notes
for insert with check (public.is_client_member(client_id));
 drop policy if exists notes_member_update on public.client_notes;
create policy notes_member_update on public.client_notes
for update using (public.is_client_member(client_id)) with check (public.is_client_member(client_id));

-- comments
 drop policy if exists comments_member_select on public.ig_comments;
create policy comments_member_select on public.ig_comments
for select using (public.is_client_member(client_id));

-- media
 drop policy if exists media_member_select on public.ig_media;
create policy media_member_select on public.ig_media
for select using (public.is_client_member(client_id));

-- snapshots
 drop policy if exists snapshots_member_select on public.ig_profile_snapshots;
create policy snapshots_member_select on public.ig_profile_snapshots
for select using (public.is_client_member(client_id::text));
