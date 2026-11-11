-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Briefing (porta de entrada dos pedidos): a pessoa digita o pedido, a IA monta um briefing curto com o contexto
-- do cliente e a equipe distribui para as telas (Social Media, Mídia On, Clipping, Redação, Criadores) e cria a
-- tarefa de cada pessoa. O cliente também abre briefing: fica "aguardando equipe" até a Mugô aprovar.
create table if not exists public.studio_briefs (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  request text not null check (length(request) between 3 and 4000),
  links jsonb not null default '[]'::jsonb check (jsonb_typeof(links) = 'array'),
  status text not null default 'pronto' check (status in ('aguardando_equipe', 'pronto', 'distribuido', 'arquivado')),
  brief jsonb not null default '{}'::jsonb check (jsonb_typeof(brief) = 'object'),
  destinations jsonb not null default '{}'::jsonb check (jsonb_typeof(destinations) = 'object'),
  tasks jsonb not null default '[]'::jsonb check (jsonb_typeof(tasks) = 'array'),
  created_by uuid,
  created_by_name text check (created_by_name is null or length(created_by_name) <= 120),
  created_side text not null default 'mugo' check (created_side in ('mugo', 'cliente')),
  approved_by uuid,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists studio_briefs_client_idx on public.studio_briefs (client_id, created_at desc);

alter table public.studio_briefs enable row level security;
revoke all on public.studio_briefs from anon, authenticated;
grant all on public.studio_briefs to service_role;

notify pgrst, 'reload schema';
