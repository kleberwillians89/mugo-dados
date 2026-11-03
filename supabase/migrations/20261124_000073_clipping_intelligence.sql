-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Clipping Intelligence: evolui o clipping existente (studio_clipping_*), sem módulo paralelo.
-- news_articles é catálogo PÚBLICO compartilhado (notícia + texto extraído, coletado uma vez);
-- a análise (relevância, sentimento, riscos...) fica em studio_clippings, isolada por client_id.

create table if not exists public.news_articles (
 url_hash text primary key check (length(url_hash) = 40),
 url text not null check (length(url) <= 2000),
 title text not null check (length(title) between 1 and 400),
 source text check (source is null or length(source) <= 160),
 published_at timestamptz,
 excerpt text check (excerpt is null or length(excerpt) <= 1500),
 content_text text check (content_text is null or length(content_text) <= 1500),
 provider text not null default 'rss' check (provider in ('rss', 'google_news', 'gdelt')),
 fetched_at timestamptz not null default now()
);
create index if not exists news_articles_published_idx on public.news_articles (published_at desc nulls last);

-- Radar por cliente
alter table public.studio_clipping_settings
  add column if not exists people text[] not null default '{}',
  add column if not exists keywords text[] not null default '{}',
  add column if not exists themes text[] not null default '{}',
  add column if not exists feeds text[] not null default '{}',
  add column if not exists region text check (region is null or length(region) <= 120),
  add column if not exists relevance_criteria text check (relevance_criteria is null or length(relevance_criteria) <= 1000),
  add column if not exists min_relevance integer not null default 40 check (min_relevance between 0 and 100),
  add column if not exists ai_daily_limit integer not null default 60 check (ai_daily_limit between 0 and 500);

-- Análise por cliente
alter table public.studio_clippings drop constraint if exists studio_clippings_kind_check;
alter table public.studio_clippings add constraint studio_clippings_kind_check check (kind in ('marca', 'concorrente', 'pessoa', 'tema'));
alter table public.studio_clippings drop constraint if exists studio_clippings_sentiment_check;
alter table public.studio_clippings add constraint studio_clippings_sentiment_check check (sentiment is null or sentiment in ('positivo', 'neutro', 'negativo', 'misto'));
alter table public.studio_clippings drop constraint if exists studio_clippings_summary_check;
alter table public.studio_clippings add constraint studio_clippings_summary_check check (summary is null or length(summary) <= 700);
alter table public.studio_clippings
  add column if not exists relevance integer check (relevance is null or relevance between 0 and 100),
  add column if not exists criticality text check (criticality is null or criticality in ('baixa', 'media', 'alta', 'critica')),
  add column if not exists main_theme text check (main_theme is null or length(main_theme) <= 80),
  add column if not exists entities text[] not null default '{}',
  add column if not exists opportunities text[] not null default '{}',
  add column if not exists risks text[] not null default '{}',
  add column if not exists justification text check (justification is null or length(justification) <= 700),
  add column if not exists evidence text[] not null default '{}',
  add column if not exists analyzed_at timestamptz,
  add column if not exists alert_status text not null default 'nenhum' check (alert_status in ('nenhum', 'enfileirado', 'revisao'));
create index if not exists studio_clippings_relevance_idx on public.studio_clippings (client_id, relevance desc nulls last);

-- Consumo de IA por cliente e dia (limite em studio_clipping_settings.ai_daily_limit)
create table if not exists public.clipping_ai_usage (
 client_id text not null references public.clients(id) on delete cascade,
 day date not null,
 calls integer not null default 0,
 items integer not null default 0,
 primary key (client_id, day)
);

alter table public.news_articles enable row level security;
alter table public.clipping_ai_usage enable row level security;
revoke all on public.news_articles, public.clipping_ai_usage from anon, authenticated;
grant all on public.news_articles, public.clipping_ai_usage to service_role;

-- Alerta interno de matéria crítica (só equipe). Fica bloqueado até o template existir e ser aprovado na Meta.
do $$
begin
  if to_regclass('public.automation_definitions') is not null then
    insert into public.automation_definitions (key, template_name, owner, audience, expected_category, trigger_label, recipients, variable_map, notes)
    values ('clipping_critico', 'mugo_alerta_clipping', 'dados', 'equipe', 'UTILITY', 'Matéria crítica no clipping (só equipe)',
            '{"team":"campaign_alerts"}', '{nome,marca,titulo,criticidade}', 'Nunca vai para cliente: crise e notícia negativa passam por revisão humana.')
    on conflict (key) do nothing;
  end if;
end $$;

notify pgrst, 'reload schema';
