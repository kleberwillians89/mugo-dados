-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Social Media (antes Redação): Matriz de Conteúdo trazida da iAgência + calendário multiplataforma.
--
-- 1) Calendário aceita outras plataformas além do Instagram. A publicação automática continua só
--    no Instagram; nas demais o post é agendado e, na hora, fica marcado para publicar à mão.
-- 2) Nova origem 'matriz' para pautas vindas da Matriz: o "Gerar mês" só troca rascunhos com
--    origem 'ia', então o que veio da Matriz nunca é apagado por uma nova geração do mês.
-- 3) Matriz de conteúdo: uma geração (matriz) com as oportunidades por plataforma, pilar e semana.
--    Exportar é idempotente: cada oportunidade gera no máximo uma pauta (índice único).
-- Mesmo padrão das tabelas do Studio: RLS ligado, só o service_role (backend) lê e grava,
-- e o backend sempre filtra por client_id.

alter table public.studio_calendar_items drop constraint if exists studio_calendar_items_channel_check;
alter table public.studio_calendar_items add constraint studio_calendar_items_channel_check
  check (channel in ('instagram', 'facebook', 'tiktok', 'linkedin', 'youtube'));

alter table public.studio_calendar_items drop constraint if exists studio_calendar_items_origin_check;
alter table public.studio_calendar_items add constraint studio_calendar_items_origin_check
  check (origin in ('ia', 'manual', 'importado', 'matriz'));

create table if not exists public.studio_content_matrices (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  week_start date not null,
  platforms text[] not null default '{instagram}',
  pillars jsonb not null default '[]'::jsonb,
  focus text check (focus is null or length(focus) <= 1000),
  summary text check (summary is null or length(summary) <= 1200),
  notes jsonb not null default '[]'::jsonb,
  status text not null default 'ativa' check (status in ('ativa', 'arquivada')),
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists studio_content_matrices_client_idx on public.studio_content_matrices (client_id, created_at desc);

create table if not exists public.studio_matrix_opportunities (
  id uuid primary key default gen_random_uuid(),
  matrix_id uuid not null references public.studio_content_matrices(id) on delete cascade,
  client_id text not null references public.clients(id) on delete cascade,
  platform text not null check (platform in ('instagram', 'facebook', 'tiktok', 'linkedin', 'youtube')),
  pillar text not null check (length(pillar) between 1 and 120),
  week smallint not null check (week between 1 and 4),
  weekday smallint not null default 1 check (weekday between 0 and 6),
  format text not null check (format in ('reels', 'carrossel', 'imagem', 'stories', 'video')),
  title text not null check (length(title) between 1 and 200),
  hook text check (hook is null or length(hook) <= 400),
  angle text check (angle is null or length(angle) <= 600),
  caption_draft text check (caption_draft is null or length(caption_draft) <= 4000),
  rationale text check (rationale is null or length(rationale) <= 1200),
  guard jsonb not null default '[]'::jsonb,
  status text not null default 'sugerida' check (status in ('sugerida', 'selecionada', 'descartada', 'exportada')),
  edited boolean not null default false,
  position smallint not null default 0,
  calendar_item_id uuid references public.studio_calendar_items(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists studio_matrix_opportunities_matrix_idx on public.studio_matrix_opportunities (matrix_id, week, platform, position);
create index if not exists studio_matrix_opportunities_client_idx on public.studio_matrix_opportunities (client_id);

-- Uma oportunidade vira no máximo uma pauta, mesmo com dois cliques ou duas abas ao mesmo tempo.
alter table public.studio_calendar_items add column if not exists matrix_opportunity_id uuid
  references public.studio_matrix_opportunities(id) on delete set null;
create unique index if not exists studio_calendar_items_matrix_opportunity_uidx
  on public.studio_calendar_items (matrix_opportunity_id) where matrix_opportunity_id is not null;

alter table public.studio_content_matrices enable row level security;
alter table public.studio_matrix_opportunities enable row level security;
revoke all on public.studio_content_matrices, public.studio_matrix_opportunities from anon, authenticated;
grant all on public.studio_content_matrices, public.studio_matrix_opportunities to service_role;

notify pgrst, 'reload schema';
