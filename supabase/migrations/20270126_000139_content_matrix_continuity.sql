-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva e retrocompatível.
-- Continuidade da Matriz Tática: briefing vinculado, quantidade planejada e aprovação interna versionada.

alter table public.studio_content_matrices
  add column if not exists brief_id uuid references public.studio_briefs(id) on delete set null,
  add column if not exists brief_snapshot jsonb,
  add column if not exists target_count smallint check (target_count is null or target_count between 1 and 80),
  add column if not exists approval_status text not null default 'rascunho'
    check (approval_status in ('rascunho', 'em_revisao', 'aprovada', 'ajuste_solicitado')),
  add column if not exists approval_version integer not null default 0 check (approval_version >= 0);

create index if not exists studio_content_matrices_brief_idx
  on public.studio_content_matrices (client_id, brief_id) where brief_id is not null;

create table if not exists public.studio_matrix_approval_events (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  matrix_id uuid not null references public.studio_content_matrices(id) on delete cascade,
  opportunity_id uuid references public.studio_matrix_opportunities(id) on delete set null,
  version integer not null check (version >= 1),
  action text not null check (action in ('enviada', 'comentario', 'aprovada', 'ajuste_solicitado')),
  comment text check (comment is null or length(comment) <= 2000),
  snapshot jsonb,
  actor_id uuid,
  actor_name text check (actor_name is null or length(actor_name) <= 120),
  created_at timestamptz not null default now()
);
create index if not exists studio_matrix_approval_events_matrix_idx
  on public.studio_matrix_approval_events (client_id, matrix_id, version, created_at);

alter table public.studio_matrix_approval_events enable row level security;
revoke all on public.studio_matrix_approval_events from anon, authenticated;
grant all on public.studio_matrix_approval_events to service_role;

notify pgrst, 'reload schema';
