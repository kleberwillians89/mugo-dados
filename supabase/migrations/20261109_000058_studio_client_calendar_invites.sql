-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Calendário do cliente + aviso ao time + convite "quer ver o resumo?".
--
-- studio_calendar_items: o cliente pode editar texto e data dos posts que vê
-- (com o cliente, aprovado, publicado). client_edited_* marcam a edição para a
-- equipe conferir; nada é apagado nem reescrito por trás.
--
-- studio_team_events: cada aprovação, pedido de ajuste ou edição feita pelo
-- cliente vira um evento. O Dados manda para o CRM (tarefa + WhatsApp do time)
-- e guarda o resultado; o que falhar fica "pendente" e é reenviado pelo job.
--
-- studio_invites: convite "quer ver os dados da semana?" com botões Sim/Não.
-- O clique volta pelo CRM (id da mensagem original) e o resumo sai sozinho.
-- studio_messages ganha o tipo "convite" e os envios em texto livre ("resposta").

alter table public.studio_calendar_items add column if not exists client_edited_at timestamptz;
alter table public.studio_calendar_items add column if not exists client_edited_by uuid;
alter table public.studio_calendar_items add column if not exists client_edited_fields text[] not null default '{}';

create table if not exists public.studio_team_events (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  item_id uuid references public.studio_calendar_items(id) on delete set null,
  action text not null check (action in ('aprovado', 'ajuste_solicitado', 'editado_pelo_cliente')),
  actor_name text check (actor_name is null or length(actor_name) <= 120),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'pendente' check (status in ('pendente', 'enviado', 'ignorado')),
  attempts integer not null default 0,
  last_error text check (last_error is null or length(last_error) <= 80),
  crm_task_id text check (crm_task_id is null or length(crm_task_id) <= 80),
  created_at timestamptz not null default now(),
  sent_at timestamptz
);
create index if not exists studio_team_events_pending_idx on public.studio_team_events (status, created_at) where status = 'pendente';
create index if not exists studio_team_events_client_idx on public.studio_team_events (client_id, created_at desc);
alter table public.studio_team_events enable row level security;
revoke all on public.studio_team_events from anon, authenticated;
grant all on public.studio_team_events to service_role;

create table if not exists public.studio_invites (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  contact_id uuid references public.studio_client_contacts(id) on delete set null,
  report_kind text not null check (report_kind in ('trafego', 'semanal', 'resultados')),
  provider_message_id text check (provider_message_id is null or length(provider_message_id) <= 200),
  status text not null default 'aguardando' check (status in ('aguardando', 'sim', 'nao', 'enviado', 'falhou', 'expirado')),
  answer_message_id text check (answer_message_id is null or length(answer_message_id) <= 200),
  error_code text check (error_code is null or length(error_code) <= 80),
  sent_by uuid,
  created_at timestamptz not null default now(),
  answered_at timestamptz,
  delivered_at timestamptz
);
create unique index if not exists studio_invites_provider_message_uidx on public.studio_invites (provider_message_id) where provider_message_id is not null;
create unique index if not exists studio_invites_answer_uidx on public.studio_invites (answer_message_id) where answer_message_id is not null;
create index if not exists studio_invites_client_idx on public.studio_invites (client_id, created_at desc);
alter table public.studio_invites enable row level security;
revoke all on public.studio_invites from anon, authenticated;
grant all on public.studio_invites to service_role;

alter table public.studio_messages drop constraint if exists studio_messages_kind_check;
alter table public.studio_messages add constraint studio_messages_kind_check
  check (kind in ('aprovacao', 'lembrete', 'agenda', 'trafego', 'resultados', 'semanal', 'convite'));

notify pgrst, 'reload schema';
