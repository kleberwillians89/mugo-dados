-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva (reversão no fim do arquivo).
-- Metas inteligentes: direção (mínima ou máxima), meta principal, submetas ligadas à meta de origem, responsável,
-- premissas da sugestão escolhida, novos indicadores com fonte verificável e histórico de alterações.
alter table public.client_goals drop constraint if exists client_goals_metric_check;
alter table public.client_goals add constraint client_goals_metric_check check (metric in (
  'revenue','orders','average_ticket','ad_spend','roas','conversions','followers','reach','impressions','engagement',
  'cpa_meta','google_conversions','sessions','conversion_rate','followers_gained'));

alter table public.client_goals
  add column if not exists direction text not null default 'min' check (direction in ('min','max')),
  add column if not exists is_primary boolean not null default false,
  add column if not exists parent_goal_id uuid references public.client_goals(id) on delete set null,
  add column if not exists relation text check (relation is null or length(relation) <= 160),
  add column if not exists owner_user_id text check (owner_user_id is null or length(owner_user_id) <= 80),
  add column if not exists suggestion jsonb;
create index if not exists client_goals_parent_idx on public.client_goals(parent_goal_id) where parent_goal_id is not null;

-- Histórico: criar, editar e excluir ficam registrados com o antes e o depois (a meta excluída continua no histórico).
create table if not exists public.client_goal_history (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  goal_id uuid not null,
  action text not null check (action in ('criada','editada','excluida')),
  before jsonb,
  after jsonb,
  actor text,
  created_at timestamptz not null default now()
);
create index if not exists client_goal_history_goal_idx on public.client_goal_history(goal_id, created_at desc);
alter table public.client_goal_history enable row level security;
revoke all on public.client_goal_history from anon, authenticated;
grant all on public.client_goal_history to service_role;

-- Reversão (manual, só se necessário):
-- drop table if exists public.client_goal_history;
-- alter table public.client_goals drop column if exists suggestion, drop column if exists owner_user_id,
--   drop column if exists relation, drop column if exists parent_goal_id, drop column if exists is_primary, drop column if exists direction;
-- (antes de restaurar o check antigo de metric, apague ou converta as metas com os indicadores novos)
