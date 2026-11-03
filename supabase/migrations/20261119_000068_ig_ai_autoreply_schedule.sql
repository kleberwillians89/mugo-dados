-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- 1) IA responde comentários do Instagram sozinha, no tom de cada marca (ligada por padrão para todos).
-- 2) Agendamento confirmado pela equipe depois que o cliente aprova a publicação.

alter table public.ig_engagement_actions drop constraint if exists ig_engagement_actions_kind_check;
alter table public.ig_engagement_actions add constraint ig_engagement_actions_kind_check
  check (kind in ('resposta_publica', 'direct', 'resposta_manual', 'resposta_ia', 'revisao'));
alter table public.ig_engagement_actions drop constraint if exists ig_engagement_actions_status_check;
alter table public.ig_engagement_actions add constraint ig_engagement_actions_status_check
  check (status in ('enviado', 'simulado', 'falhou', 'pendente'));
-- Uma resposta da IA (ou um pedido de revisão) por comentário, mesmo com dois jobs ao mesmo tempo.
create unique index if not exists ig_engagement_actions_ai_once_idx
  on public.ig_engagement_actions (client_id, comment_id, kind)
  where kind in ('resposta_ia', 'revisao') and status in ('enviado', 'simulado', 'pendente');

create table if not exists public.ig_engagement_settings (
  client_id text primary key references public.clients(id) on delete cascade,
  ai_autoreply boolean not null default true,
  max_per_run integer not null default 10 check (max_per_run between 1 and 30),
  updated_by text,
  updated_at timestamptz not null default now()
);
alter table public.ig_engagement_settings enable row level security;
revoke all on public.ig_engagement_settings from anon, authenticated;
grant all on public.ig_engagement_settings to service_role;

alter table public.studio_calendar_items
  add column if not exists schedule_confirmed_at timestamptz,
  add column if not exists schedule_confirmed_by text;

notify pgrst, 'reload schema';
