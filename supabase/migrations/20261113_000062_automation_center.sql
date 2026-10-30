-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Central de Automações: catálogo de templates (sincronizado da Meta), definição das automações,
-- fila persistente e idempotente, respostas, preferências/consentimento, equipe Mugô e Google Calendar.
--
-- Envio continua pelo número oficial da Mugô (MugôZap/WhatsApp Cloud API, via CRM).
-- Nada aqui é lido pelo navegador: tudo passa pelo backend (service_role) com papel de agência.

-- ---------------------------------------------------------------- OAuth do Google Calendar
alter table public.oauth_sessions drop constraint if exists oauth_sessions_provider_check;
alter table public.oauth_sessions add constraint oauth_sessions_provider_check
  check (provider in ('meta', 'google', 'shopify', 'google_calendar'));

-- ---------------------------------------------------------------- catálogo da Meta
-- Espelho de GET /{WABA_ID}/message_templates. Status sempre o que a Meta devolveu.
create table if not exists public.whatsapp_template_catalog (
 name text not null check (name ~ '^[a-z0-9_]+$' and length(name) <= 512),
 language text not null check (length(language) between 2 and 15),
 category text,
 status text not null,
 rejected_reason text,
 body_param_count integer not null default 0 check (body_param_count >= 0),
 header_format text,
 button_url_dynamic boolean not null default false,
 quick_replies text[] not null default '{}',
 components jsonb not null default '[]'::jsonb,
 meta_template_id text,
 synced_at timestamptz not null default now(),
 primary key (name, language)
);

-- ---------------------------------------------------------------- automações
create table if not exists public.automation_definitions (
 key text primary key check (key ~ '^[a-z0-9_]{1,80}$'),
 template_name text not null check (template_name ~ '^[a-z0-9_]+$' and length(template_name) <= 512),
 language text not null default 'pt_BR',
 -- dados: o Dados dispara. crm: o CRM já dispara (o Dados só mostra, nunca envia: evita duplicidade).
 -- tecnico: template de teste, sem disparo automático.
 owner text not null check (owner in ('dados', 'crm', 'tecnico')),
 audience text not null check (audience in ('cliente', 'equipe', 'lead')),
 expected_category text not null default 'UTILITY' check (expected_category in ('UTILITY', 'MARKETING', 'AUTHENTICATION')),
 trigger_label text not null,
 automation_enabled boolean not null default true,
 schedule jsonb not null default '{}'::jsonb,
 lead_minutes integer check (lead_minutes is null or lead_minutes between 0 and 20160),
 recipients jsonb not null default '{}'::jsonb,
 variable_map text[] not null default '{}',
 crm_reference text,
 notes text,
 updated_by text,
 updated_at timestamptz not null default now()
);

-- Equipe Mugô que recebe avisos internos (reuniões internas, alerta de campanha). Telefone precisa
-- existir também no CRM (o MugôZap recusa número desconhecido).
create table if not exists public.automation_team_members (
 id uuid primary key default gen_random_uuid(),
 name text not null check (length(trim(name)) between 1 and 120),
 email text not null check (email = lower(email) and email ~ '^[^@\s]+@[^@\s]+$'),
 phone text check (phone is null or phone ~ '^[0-9]{10,15}$'),
 active boolean not null default true,
 receives_internal boolean not null default true,
 receives_campaign_alerts boolean not null default false,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique (email)
);

-- Consentimento e preferências por telefone. Marketing exige opt-in explícito.
create table if not exists public.automation_recipient_prefs (
 phone text primary key check (phone ~ '^[0-9]{10,15}$'),
 opted_out boolean not null default false,
 marketing_opt_in boolean not null default false,
 marketing_opt_in_at timestamptz,
 source text,
 updated_at timestamptz not null default now()
);

-- E-mail do contato do cliente: mapeia participantes do Google Calendar para a empresa certa.
alter table public.studio_client_contacts add column if not exists email text
  check (email is null or (email = lower(email) and email ~ '^[^@\s]+@[^@\s]+$'));
create index if not exists studio_client_contacts_email_idx on public.studio_client_contacts (email) where email is not null;

-- ---------------------------------------------------------------- fila
create table if not exists public.automation_outbox (
 id uuid primary key default gen_random_uuid(),
 automation_key text not null references public.automation_definitions(key) on delete restrict,
 template_name text not null,
 language text not null default 'pt_BR',
 client_id text references public.clients(id) on delete cascade,
 audience text not null check (audience in ('cliente', 'equipe', 'lead')),
 recipient_ref text,
 recipient_name text check (recipient_name is null or length(recipient_name) <= 120),
 recipient_phone text not null check (recipient_phone ~ '^[0-9]{10,15}$'),
 params jsonb not null default '{}'::jsonb,
 button_suffix text,
 source_type text not null check (length(source_type) between 1 and 40),
 source_id text not null check (length(source_id) between 1 and 200),
 idempotency_key text not null unique check (length(idempotency_key) between 16 and 120),
 scheduled_for timestamptz not null default now(),
 status text not null default 'agendado'
   check (status in ('agendado', 'processando', 'enviado', 'falhou', 'cancelado', 'bloqueado', 'simulado')),
 attempts integer not null default 0,
 next_attempt_at timestamptz,
 claim_token uuid,
 claimed_at timestamptz,
 last_error text check (last_error is null or length(last_error) <= 300),
 provider_message_id text,
 delivery_status text check (delivery_status is null or delivery_status in ('accepted', 'sent', 'delivered', 'read', 'failed')),
 delivery_updated_at timestamptz,
 sent_at timestamptz,
 cancelled_reason text,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create index if not exists automation_outbox_due_idx on public.automation_outbox (status, scheduled_for);
create index if not exists automation_outbox_source_idx on public.automation_outbox (source_type, source_id);
create index if not exists automation_outbox_client_idx on public.automation_outbox (client_id, created_at desc);
create unique index if not exists automation_outbox_provider_idx on public.automation_outbox (provider_message_id) where provider_message_id is not null;

-- Pega lotes com trava (SKIP LOCKED): dois workers nunca processam a mesma linha.
-- Linha presa em "processando" há mais de 10 min volta para a fila (worker caiu no meio).
create or replace function public.claim_automation_outbox(p_limit integer, p_token uuid)
returns setof public.automation_outbox
language sql
security definer
set search_path = public
as $$
  update public.automation_outbox o
     set status = 'processando', claim_token = p_token, claimed_at = now(), updated_at = now()
   where o.id in (
     select id from public.automation_outbox
      where (status = 'agendado' and scheduled_for <= now() and (next_attempt_at is null or next_attempt_at <= now()))
         or (status = 'processando' and claimed_at < now() - interval '10 minutes')
      order by scheduled_for
      limit greatest(1, least(p_limit, 100))
      for update skip locked
   )
  returning o.*;
$$;
revoke all on function public.claim_automation_outbox(integer, uuid) from public, anon, authenticated;
grant execute on function public.claim_automation_outbox(integer, uuid) to service_role;

-- Respostas recebidas (botões/texto), repassadas pelo webhook do WhatsApp via CRM.
create table if not exists public.automation_responses (
 id uuid primary key default gen_random_uuid(),
 provider_message_id text not null unique,
 context_message_id text,
 outbox_id uuid references public.automation_outbox(id) on delete set null,
 client_id text references public.clients(id) on delete cascade,
 phone_masked text,
 answer_raw text check (answer_raw is null or length(answer_raw) <= 200),
 answer_key text,
 result text check (result is null or length(result) <= 300),
 received_at timestamptz not null default now()
);
create index if not exists automation_responses_client_idx on public.automation_responses (client_id, received_at desc);

-- ---------------------------------------------------------------- Google Calendar (conta corporativa)
create table if not exists public.google_calendar_connection (
 id text primary key default 'mugo' check (id = 'mugo'),
 account_email text,
 refresh_token_enc text,
 access_token_enc text,
 access_expires_at timestamptz,
 scopes text[] not null default '{}',
 calendar_id text,
 calendar_summary text,
 sync_token text,
 channel_id text,
 channel_resource_id text,
 channel_token_hash text,
 channel_expires_at timestamptz,
 status text not null default 'desconectado'
   check (status in ('desconectado', 'aguardando_calendario', 'ativo', 'reautorizar', 'erro')),
 last_sync_at timestamptz,
 last_error text check (last_error is null or length(last_error) <= 300),
 connected_by text,
 updated_at timestamptz not null default now()
);

create table if not exists public.calendar_events (
 id uuid primary key default gen_random_uuid(),
 calendar_id text not null,
 google_event_id text not null,
 status text not null check (status in ('confirmed', 'tentative', 'cancelled')),
 summary text,
 start_at timestamptz,
 end_at timestamptz,
 all_day boolean not null default false,
 timezone text,
 organizer_email text,
 attendees jsonb not null default '[]'::jsonb,
 kind text not null default 'outro' check (kind in ('interna', 'cliente', 'outro')),
 client_id text references public.clients(id) on delete set null,
 html_link text,
 etag text,
 google_updated_at timestamptz,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique (calendar_id, google_event_id)
);
create index if not exists calendar_events_start_idx on public.calendar_events (start_at);
create index if not exists calendar_events_client_idx on public.calendar_events (client_id, start_at);

-- ---------------------------------------------------------------- segurança
alter table public.whatsapp_template_catalog enable row level security;
alter table public.automation_definitions enable row level security;
alter table public.automation_team_members enable row level security;
alter table public.automation_recipient_prefs enable row level security;
alter table public.automation_outbox enable row level security;
alter table public.automation_responses enable row level security;
alter table public.google_calendar_connection enable row level security;
alter table public.calendar_events enable row level security;
revoke all on public.whatsapp_template_catalog, public.automation_definitions, public.automation_team_members,
  public.automation_recipient_prefs, public.automation_outbox, public.automation_responses,
  public.google_calendar_connection, public.calendar_events from anon, authenticated;
grant all on public.whatsapp_template_catalog, public.automation_definitions, public.automation_team_members,
  public.automation_recipient_prefs, public.automation_outbox, public.automation_responses,
  public.google_calendar_connection, public.calendar_events to service_role;

drop trigger if exists automation_definitions_updated_at on public.automation_definitions;
create trigger automation_definitions_updated_at before update on public.automation_definitions for each row execute function public.set_updated_at();
drop trigger if exists automation_team_members_updated_at on public.automation_team_members;
create trigger automation_team_members_updated_at before update on public.automation_team_members for each row execute function public.set_updated_at();
drop trigger if exists automation_outbox_updated_at on public.automation_outbox;
create trigger automation_outbox_updated_at before update on public.automation_outbox for each row execute function public.set_updated_at();
drop trigger if exists calendar_events_updated_at on public.calendar_events;
create trigger calendar_events_updated_at before update on public.calendar_events for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------- automações cadastradas
-- automation_enabled = true conforme pedido; owner decide QUEM dispara. Status de aprovação NÃO fica aqui:
-- vem do catálogo sincronizado da Meta. variable_map é a ordem das variáveis {{1}}, {{2}}...; o motor confere
-- a quantidade com a Meta antes de enviar e bloqueia se não bater.
insert into public.automation_definitions (key, template_name, owner, audience, expected_category, trigger_label, schedule, lead_minutes, recipients, variable_map, crm_reference, notes) values
 ('reuniao_interna', 'mugo_reuniao_interna', 'dados', 'equipe', 'UTILITY', 'Reunião interna agendada (Google Calendar)', '{}', 1440, '{"from":"calendar_attendees"}', '{nome,titulo,data,hora}', null, null),
 ('resumo_diario', 'mugo_resumo_diario', 'crm', 'equipe', 'UTILITY', 'Resumo diário às 08h (seg a sex)', '{"time":"08:00","weekdays":[1,2,3,4,5]}', null, '{}', '{}', 'team-daily-brief-worker', 'O CRM envia hoje com o template mugo_resumo_diario_equipe.'),
 ('aprovacao_recebida', 'mugo_aprovacao_recebida', 'crm', 'equipe', 'UTILITY', 'Cliente aprovou ou pediu ajuste', '{}', null, '{}', '{}', 'dados-ops-events content_feedback → team-notification-worker', 'O Dados já registra e repassa ao CRM, que cria a tarefa e avisa o responsável.'),
 ('tarefa_atribuida', 'mugo_tarefa_atribuida', 'crm', 'equipe', 'UTILITY', 'Nova tarefa atribuída', '{}', null, '{}', '{}', 'team-notification-worker task_assigned (MUGO_TEAM_ALERT_TEMPLATE_NAME)', null),
 ('tarefa_prazo', 'mugo_tarefa_prazo', 'crm', 'equipe', 'UTILITY', 'Tarefa próxima do vencimento', '{}', null, '{}', '{}', 'task-reminder-worker', 'O CRM usa hoje mugo_lembrete_tarefa.'),
 ('reuniao_lembrete', 'mugo_reuniao_lembrete', 'dados', 'cliente', 'UTILITY', 'Reunião com cliente (Google Calendar)', '{}', 1440, '{"from":"calendar_attendees"}', '{nome,marca,titulo,data,hora}', null, null),
 ('conteudo_publicado', 'mugo_conteudo_publicado', 'dados', 'cliente', 'UTILITY', 'Conteúdo efetivamente publicado (confirmado no Instagram)', '{}', null, '{"receives":"conteudo"}', '{nome,marca,titulo,link}', null, null),
 ('alerta_campanha', 'mugo_alerta_campanha', 'dados', 'equipe', 'UTILITY', 'Ocorrência confirmada em campanha (só equipe)', '{}', null, '{"team":"campaign_alerts"}', '{nome,marca,campanha,ocorrencia}', null, 'Nunca vai para cliente.'),
 ('ajuste_concluido', 'mugo_ajuste_concluido', 'dados', 'cliente', 'UTILITY', 'Ajustes finalizados', '{}', null, '{"receives":"conteudo"}', '{nome,marca,titulo}', null, null),
 ('relatorio_pronto', 'mugo_relatorio_pronto', 'dados', 'cliente', 'UTILITY', 'Relatório disponibilizado', '{}', null, '{"receives":"resultados"}', '{nome,marca,periodo}', null, null),
 ('agenda_semana', 'mugo_agenda_semana', 'dados', 'cliente', 'UTILITY', 'Agenda semanal confirmada', '{}', null, '{"receives":"conteudo"}', '{nome,marca,semana,quantidade,destaque}', null, 'Envio pela tela Aprovação → Mensagens.'),
 ('lembrete_aprovacao', 'mugo_lembrete_aprovacao', 'dados', 'cliente', 'UTILITY', 'Conteúdos aguardando aprovação', '{"time":"10:00","weekdays":[1,2,3,4,5]}', 2880, '{"receives":"conteudo"}', '{nome,pendentes,marca,validade}', null, 'lead_minutes = intervalo mínimo entre lembretes do mesmo pedido.'),
 ('conteudo_aprovacao', 'mugo_conteudo_aprovacao', 'dados', 'cliente', 'UTILITY', 'Novos conteúdos enviados para aprovação', '{}', null, '{"receives":"conteudo"}', '{nome,quantidade,mes,marca,validade}', null, 'Envio pela tela Aprovação (link seguro com validade).'),
 ('convite_resumo', 'mugo_convite_resumo', 'dados', 'cliente', 'UTILITY', 'Sexta: convite para receber o resumo', '{"time":"10:15","weekdays":[5]}', null, '{"receives":"trafego"}', '{nome,marca,periodo}', null, 'Respostas: Resumo semanal / Período completo / Agora não.'),
 ('cobranca_link', 'mugo_cobranca_link_v1', 'crm', 'cliente', 'UTILITY', 'Mensalidade disponível para pagamento', '{}', null, '{}', '{}', 'collection-cadence-worker (Asaas)', null),
 ('alerta_equipe', 'mugo_alerta_equipe', 'crm', 'equipe', 'UTILITY', 'Atualização interna autorizada', '{}', null, '{}', '{}', 'team-notification-worker', null),
 ('boas_vindas_diagnostico', 'mugo_boas_vindas_diagnostico_v1', 'crm', 'lead', 'MARKETING', 'Novo lead com consentimento', '{}', null, '{}', '{}', 'CRM comercial (leads)', 'Marketing: só com opt-in.'),
 ('agendamento_confirmado', 'mugo_agendamento_confirmado', 'dados', 'cliente', 'UTILITY', 'Atendimento confirmado (participante aceitou no Google Calendar)', '{}', null, '{"from":"calendar_attendees"}', '{nome,dia,hora}', null, null),
 ('aviso_renovacao_contrato', 'mugo_aviso_renovacao_contrato', 'crm', 'cliente', 'UTILITY', 'Renovação contratual próxima', '{}', null, '{}', '{}', 'CRM financeiro', null),
 ('solicitar_comprovante', 'mugo_solicitar_comprovante', 'crm', 'cliente', 'UTILITY', 'Comprovante solicitado', '{}', null, '{}', '{}', 'CRM financeiro', null),
 ('pagamento_confirmado', 'mugo_pagamento_confirmado', 'crm', 'cliente', 'UTILITY', 'Pagamento confirmado', '{}', null, '{}', '{}', 'asaas-webhook', null),
 ('alerta_pagamento_pendente', 'mugo_alerta_pagamento_pendente', 'crm', 'cliente', 'UTILITY', 'Pendência financeira verificada', '{}', null, '{}', '{}', 'collection-cadence-worker / collection-notification-worker', null)
on conflict (key) do nothing;

insert into public.automation_definitions (key, template_name, owner, audience, expected_category, trigger_label, automation_enabled, notes) values
 ('hello_world', 'hello_world', 'tecnico', 'equipe', 'UTILITY', 'Template técnico de teste da Meta', false, 'Sem disparo automático em produção.')
on conflict (key) do nothing;

notify pgrst, 'reload schema';
