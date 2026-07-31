-- Instagram organic persistence alignment for cliente delivery.
-- Keeps legacy tables compatible with the current Graph sync payload.

create table if not exists public.ig_profile_snapshots (
  id bigserial primary key,
  client_id text not null,
  connection_id uuid,
  snapshot_date date not null,
  followers_count integer not null default 0,
  media_count integer not null default 0,
  impressions_day integer not null default 0,
  reach_day integer not null default 0,
  total_interactions_day integer not null default 0,
  website_clicks_day integer not null default 0,
  profile_views_day integer not null default 0,
  accounts_engaged_day integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, snapshot_date)
);

alter table if exists public.ig_profile_snapshots
  add column if not exists connection_id uuid,
  add column if not exists followers_count integer not null default 0,
  add column if not exists media_count integer not null default 0,
  add column if not exists impressions_day integer not null default 0,
  add column if not exists reach_day integer not null default 0,
  add column if not exists total_interactions_day integer not null default 0,
  add column if not exists website_clicks_day integer not null default 0,
  add column if not exists profile_views_day integer not null default 0,
  add column if not exists accounts_engaged_day integer not null default 0,
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();

create table if not exists public.ig_media (
  id bigserial primary key,
  client_id text not null,
  connection_id uuid,
  media_id text not null,
  media_type text,
  media_product_type text,
  caption text,
  permalink text,
  timestamp timestamptz,
  thumb_url text,
  media_url text,
  thumbnail_url text,
  insights_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, media_id)
);

alter table if exists public.ig_media
  add column if not exists connection_id uuid,
  add column if not exists media_type text,
  add column if not exists media_product_type text,
  add column if not exists caption text,
  add column if not exists permalink text,
  add column if not exists timestamp timestamptz,
  add column if not exists thumb_url text,
  add column if not exists media_url text,
  add column if not exists thumbnail_url text,
  add column if not exists insights_json jsonb not null default '{}'::jsonb,
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();

create table if not exists public.ig_comments (
  id bigserial primary key,
  client_id text not null,
  connection_id uuid,
  media_id text not null,
  comment_id text not null,
  username text,
  text text,
  like_count integer,
  timestamp timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, comment_id)
);

alter table if exists public.ig_comments
  add column if not exists connection_id uuid,
  add column if not exists username text,
  add column if not exists text text,
  add column if not exists like_count integer,
  add column if not exists timestamp timestamptz,
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();

do $$
begin
  if to_regclass('public.ig_profile_snapshots') is not null
     and to_regclass('public.meta_connections') is not null
     and not exists (
       select 1
       from pg_constraint c
       join pg_class t on t.oid = c.conrelid
       join pg_namespace n on n.oid = t.relnamespace
       where n.nspname = 'public'
         and t.relname = 'ig_profile_snapshots'
         and c.contype = 'f'
         and pg_get_constraintdef(c.oid) ilike '%foreign key (connection_id)%references%meta_connections(id)%'
     ) then
    alter table public.ig_profile_snapshots
      add constraint fk_ig_profile_snapshots_connection_id
      foreign key (connection_id) references public.meta_connections(id) on delete cascade not valid;
  end if;

  if to_regclass('public.ig_comments') is not null
     and to_regclass('public.meta_connections') is not null
     and not exists (
       select 1
       from pg_constraint c
       join pg_class t on t.oid = c.conrelid
       join pg_namespace n on n.oid = t.relnamespace
       where n.nspname = 'public'
         and t.relname = 'ig_comments'
         and c.contype = 'f'
         and pg_get_constraintdef(c.oid) ilike '%foreign key (connection_id)%references%meta_connections(id)%'
     ) then
    alter table public.ig_comments
      add constraint fk_ig_comments_connection_id
      foreign key (connection_id) references public.meta_connections(id) on delete cascade not valid;
  end if;

  if to_regclass('public.ig_media') is not null
     and to_regclass('public.meta_connections') is not null
     and not exists (
       select 1
       from pg_constraint c
       join pg_class t on t.oid = c.conrelid
       join pg_namespace n on n.oid = t.relnamespace
       where n.nspname = 'public'
         and t.relname = 'ig_media'
         and c.contype = 'f'
         and pg_get_constraintdef(c.oid) ilike '%foreign key (connection_id)%references%meta_connections(id)%'
     ) then
    alter table public.ig_media
      add constraint fk_ig_media_connection_id
      foreign key (connection_id) references public.meta_connections(id) on delete cascade not valid;
  end if;
end $$;

create unique index if not exists uq_ig_profile_snapshots_client_date
  on public.ig_profile_snapshots(client_id, snapshot_date);

create unique index if not exists uq_ig_profile_snapshots_client_connection_date
  on public.ig_profile_snapshots(client_id, connection_id, snapshot_date)
  where connection_id is not null;

create unique index if not exists uq_ig_media_client_media
  on public.ig_media(client_id, media_id);

create unique index if not exists uq_ig_comments_client_comment
  on public.ig_comments(client_id, comment_id);

create index if not exists idx_ig_profile_snapshots_client_date
  on public.ig_profile_snapshots(client_id, snapshot_date desc);

create index if not exists idx_ig_profile_snapshots_client_connection_date
  on public.ig_profile_snapshots(client_id, connection_id, snapshot_date desc);

create index if not exists idx_ig_media_client_connection_ts
  on public.ig_media(client_id, connection_id, timestamp desc);

create index if not exists idx_ig_media_client_product_ts
  on public.ig_media(client_id, media_product_type, timestamp desc);

create index if not exists idx_ig_comments_client_ts
  on public.ig_comments(client_id, timestamp desc);

create index if not exists idx_ig_comments_client_media
  on public.ig_comments(client_id, media_id);

do $$
begin
  if to_regprocedure('public.set_updated_at()') is null then
    execute $fn$
      create function public.set_updated_at()
      returns trigger
      language plpgsql
      as $body$
      begin
        new.updated_at = now();
        return new;
      end;
      $body$
    $fn$;
  end if;
end $$;

drop trigger if exists trg_ig_profile_snapshots_updated_at on public.ig_profile_snapshots;
create trigger trg_ig_profile_snapshots_updated_at
before update on public.ig_profile_snapshots
for each row execute function public.set_updated_at();

drop trigger if exists trg_ig_media_updated_at on public.ig_media;
create trigger trg_ig_media_updated_at
before update on public.ig_media
for each row execute function public.set_updated_at();

drop trigger if exists trg_ig_comments_updated_at on public.ig_comments;
create trigger trg_ig_comments_updated_at
before update on public.ig_comments
for each row execute function public.set_updated_at();

alter table public.ig_profile_snapshots enable row level security;
alter table public.ig_media enable row level security;
alter table public.ig_comments enable row level security;

do $$
begin
  if to_regprocedure('public.is_client_member(text)') is not null then
    drop policy if exists snapshots_member_select on public.ig_profile_snapshots;
    create policy snapshots_member_select on public.ig_profile_snapshots
      for select using (public.is_client_member(client_id::text));

    drop policy if exists media_member_select on public.ig_media;
    create policy media_member_select on public.ig_media
      for select using (public.is_client_member(client_id));

    drop policy if exists comments_member_select on public.ig_comments;
    create policy comments_member_select on public.ig_comments
      for select using (public.is_client_member(client_id));
  end if;
end $$;

notify pgrst, 'reload schema';
