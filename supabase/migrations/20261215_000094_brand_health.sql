-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Saúde da marca (Clipping → aba "Saúde da marca"): volume e sentimento das menções em notícias,
-- comentários e Direct do Instagram, por dia/semana/mês/trimestre/ano, e alertas de termos sensíveis
-- (só para a equipe Mugô). Comentário e Direct ganham sentimento/assunto classificados pela IA (job brand-health).

alter table public.ig_comments
  add column if not exists sentiment text check (sentiment is null or sentiment in ('positivo', 'neutro', 'negativo', 'misto')),
  add column if not exists theme text check (theme is null or length(theme) <= 80),
  add column if not exists analyzed_at timestamptz;
alter table public.ig_dm_messages
  add column if not exists sentiment text check (sentiment is null or sentiment in ('positivo', 'neutro', 'negativo', 'misto')),
  add column if not exists theme text check (theme is null or length(theme) <= 80),
  add column if not exists analyzed_at timestamptz;
create index if not exists ig_comments_unanalyzed_idx on public.ig_comments (client_id, timestamp desc) where analyzed_at is null;
create index if not exists ig_dm_messages_unanalyzed_idx on public.ig_dm_messages (client_id, created_at desc) where analyzed_at is null and direction = 'in';

create table if not exists public.brand_health_settings (
  client_id text primary key references public.clients(id) on delete cascade,
  sensitive_terms text[] not null default '{golpe,falsificado,procon,"reclame aqui",alergia,"não chegou",reembolso}',
  index_drop_points integer not null default 10 check (index_drop_points between 3 and 50),
  negative_day_pct integer not null default 15 check (negative_day_pct between 5 and 80),
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.brand_health_alerts (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  kind text not null check (kind in ('termo', 'queda_indice', 'negativas')),
  term text check (term is null or length(term) <= 80),
  severity text not null check (severity in ('medio', 'alto')),
  mentions integer not null default 0,
  sources text[] not null default '{}',
  sample text check (sample is null or length(sample) <= 300),
  detail text check (detail is null or length(detail) <= 300),
  status text not null default 'aberto' check (status in ('aberto', 'resolvido')),
  notified_at timestamptz,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  resolved_at timestamptz,
  resolved_by uuid
);
-- Um alerta aberto por empresa + tipo + termo: novas menções atualizam o mesmo alerta.
create unique index if not exists brand_health_alerts_open_uq
  on public.brand_health_alerts (client_id, kind, coalesce(term, '')) where status = 'aberto';
create index if not exists brand_health_alerts_client_idx on public.brand_health_alerts (client_id, last_seen_at desc);

-- Menções unificadas (notícia relevante, comentário de terceiros, mensagem recebida no Direct).
create or replace view public.brand_mentions with (security_invoker = true) as
  select c.client_id, 'news'::text as source, coalesce(c.published_at, c.created_at) as at, c.sentiment, c.main_theme as theme,
         c.title as body, c.url as link
    from public.studio_clippings c where c.relevant is not false
  union all
  select m.client_id, 'comments', coalesce(m.timestamp, m.created_at), m.sentiment, m.theme, m.text, null
    from public.ig_comments m
  union all
  select d.client_id, 'direct', d.created_at, d.sentiment, d.theme, d.text, null
    from public.ig_dm_messages d where d.direction = 'in';

-- Contagem por período agrupado (fuso de São Paulo) x canal x sentimento.
create or replace function public.brand_health_buckets(p_client text, p_start timestamptz, p_end timestamptz, p_grain text, p_sources text[])
returns table(bucket date, source text, sentiment text, n bigint)
language sql stable security invoker set search_path = public as $$
  select (date_trunc(case when p_grain in ('day','week','month','quarter','year') then p_grain else 'day' end,
                     m.at at time zone 'America/Sao_Paulo'))::date as bucket,
         m.source, coalesce(m.sentiment, 'sem_analise') as sentiment, count(*) as n
    from public.brand_mentions m
   where m.client_id = p_client and m.at >= p_start and m.at < p_end and m.source = any(p_sources)
   group by 1, 2, 3
$$;

-- Assuntos do período (normalizados em minúsculas) x sentimento.
create or replace function public.brand_health_themes(p_client text, p_start timestamptz, p_end timestamptz, p_sources text[])
returns table(theme text, sentiment text, n bigint)
language sql stable security invoker set search_path = public as $$
  select lower(trim(m.theme)) as theme, coalesce(m.sentiment, 'sem_analise'), count(*)
    from public.brand_mentions m
   where m.client_id = p_client and m.at >= p_start and m.at < p_end and m.source = any(p_sources)
     and m.theme is not null and length(trim(m.theme)) > 1
   group by 1, 2
$$;

alter table public.brand_health_settings enable row level security;
alter table public.brand_health_alerts enable row level security;
revoke all on public.brand_health_settings, public.brand_health_alerts from anon, authenticated;
revoke all on public.brand_mentions from anon, authenticated;
revoke execute on function public.brand_health_buckets(text, timestamptz, timestamptz, text, text[]) from public, anon, authenticated;
revoke execute on function public.brand_health_themes(text, timestamptz, timestamptz, text[]) from public, anon, authenticated;
grant all on public.brand_health_settings, public.brand_health_alerts to service_role;
grant select on public.brand_mentions to service_role;
grant execute on function public.brand_health_buckets(text, timestamptz, timestamptz, text, text[]) to service_role;
grant execute on function public.brand_health_themes(text, timestamptz, timestamptz, text[]) to service_role;

notify pgrst, 'reload schema';
