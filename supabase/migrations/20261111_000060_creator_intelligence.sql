-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Creator Intelligence (MVP 1): banco de criadores reutilizável + shortlists
-- isoladas por empresa + controle de consumo das fontes externas.
--
-- creators / creator_metrics guardam somente métricas PÚBLICAS e são
-- compartilhados entre empresas (o mesmo perfil não é coletado duas vezes).
-- Shortlists e itens carregam client_id e são lidos só por membros.
-- Nenhuma escrita pelo browser: tudo passa pelo backend (service_role).

create table if not exists public.creators (
 id uuid primary key default gen_random_uuid(),
 network text not null check (network in ('instagram','youtube','tiktok')),
 handle text not null check (length(trim(handle)) between 1 and 120),
 external_id text,
 display_name text,
 profile_url text,
 avatar_url text,
 biography text,
 followers bigint check (followers is null or followers >= 0),
 media_count bigint check (media_count is null or media_count >= 0),
 avg_likes numeric,
 avg_comments numeric,
 avg_views numeric,
 engagement_rate numeric,
 engagement_method text,
 sample_size integer not null default 0,
 missing_fields text[] not null default '{}',
 source text not null,
 collected_at timestamptz not null default now(),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique (network, handle)
);
create index if not exists creators_network_followers_idx on public.creators(network, followers desc nulls last);

create table if not exists public.creator_metrics (
 id uuid primary key default gen_random_uuid(),
 creator_id uuid not null references public.creators(id) on delete cascade,
 source text not null,
 collected_at timestamptz not null default now(),
 followers bigint,
 avg_likes numeric,
 avg_comments numeric,
 avg_views numeric,
 engagement_rate numeric,
 engagement_method text,
 sample_size integer not null default 0,
 recent_posts jsonb not null default '[]'::jsonb
);
create index if not exists creator_metrics_creator_idx on public.creator_metrics(creator_id, collected_at desc);

create table if not exists public.creator_shortlists (
 id uuid primary key default gen_random_uuid(),
 client_id text not null references public.clients(id) on delete cascade,
 name text not null check (length(trim(name)) between 1 and 120),
 campaign_type text not null default 'influencer' check (campaign_type in ('ugc','influencer')),
 notes text check (notes is null or length(notes) <= 2000),
 created_by text not null,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create index if not exists creator_shortlists_client_idx on public.creator_shortlists(client_id, created_at desc);

create table if not exists public.creator_shortlist_items (
 id uuid primary key default gen_random_uuid(),
 shortlist_id uuid not null references public.creator_shortlists(id) on delete cascade,
 client_id text not null references public.clients(id) on delete cascade,
 creator_id uuid not null references public.creators(id) on delete cascade,
 status text not null default 'candidate' check (status in ('candidate','contacted','approved','rejected')),
 notes text check (notes is null or length(notes) <= 2000),
 created_by text not null,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique (shortlist_id, creator_id)
);
create index if not exists creator_shortlist_items_client_idx on public.creator_shortlist_items(client_id, shortlist_id);

create table if not exists public.creator_api_usage (
 id uuid primary key default gen_random_uuid(),
 client_id text references public.clients(id) on delete set null,
 provider text not null check (provider in ('meta','youtube','apify')),
 operation text not null,
 units numeric not null default 0,
 cost_usd numeric not null default 0,
 ok boolean not null default true,
 created_at timestamptz not null default now()
);
create index if not exists creator_api_usage_provider_idx on public.creator_api_usage(provider, created_at desc);

alter table public.creators enable row level security;
alter table public.creator_metrics enable row level security;
alter table public.creator_shortlists enable row level security;
alter table public.creator_shortlist_items enable row level security;
alter table public.creator_api_usage enable row level security;

revoke all on public.creators, public.creator_metrics, public.creator_api_usage from anon, authenticated;
revoke all on public.creator_shortlists, public.creator_shortlist_items from anon, authenticated;
grant all on public.creators, public.creator_metrics, public.creator_api_usage to service_role;
grant all on public.creator_shortlists, public.creator_shortlist_items to service_role;
grant select on public.creator_shortlists, public.creator_shortlist_items to authenticated;

drop policy if exists creator_shortlists_member_read on public.creator_shortlists;
create policy creator_shortlists_member_read on public.creator_shortlists for select to authenticated using (public.is_client_member(client_id));
drop policy if exists creator_shortlist_items_member_read on public.creator_shortlist_items;
create policy creator_shortlist_items_member_read on public.creator_shortlist_items for select to authenticated using (public.is_client_member(client_id));

drop trigger if exists creators_updated_at on public.creators;
create trigger creators_updated_at before update on public.creators for each row execute function public.set_updated_at();
drop trigger if exists creator_shortlists_updated_at on public.creator_shortlists;
create trigger creator_shortlists_updated_at before update on public.creator_shortlists for each row execute function public.set_updated_at();
drop trigger if exists creator_shortlist_items_updated_at on public.creator_shortlist_items;
create trigger creator_shortlist_items_updated_at before update on public.creator_shortlist_items for each row execute function public.set_updated_at();

notify pgrst, 'reload schema';
