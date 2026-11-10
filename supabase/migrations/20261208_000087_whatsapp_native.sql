-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- WhatsApp nativo do MUGOVERSO: números das marcas ligados ao app da Mugô na Meta.
--
-- Fluxo: a Meta manda tudo para a função `whatsapp-webhook` (supabase/functions). Ela descobre a empresa
-- pelo phone_number_id, grava a conversa, a mensagem e a origem (anúncio / ref:codigo). O que for de um
-- número que não está aqui (o da Mugô, que vive no CRM Mugô) é repassado ao CRM sem alteração.
--
-- Mesmo padrão das demais tabelas: RLS ligado, só o service_role (backend e função) lê e grava, e o
-- backend sempre filtra por client_id. O token de acesso da Meta fica só aqui e nunca volta para a tela.

create table if not exists public.whatsapp_numbers (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  waba_id text not null check (waba_id ~ '^[0-9]{5,30}$'),
  phone_number_id text not null unique check (phone_number_id ~ '^[0-9]{5,30}$'),
  display_phone_number text,
  verified_name text,
  access_token text not null check (length(access_token) between 20 and 2000),
  status text not null default 'active' check (status in ('active', 'disconnected')),
  subscribed_at timestamptz,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists whatsapp_numbers_client_idx on public.whatsapp_numbers (client_id, status);

-- Uma conversa por contato por número (o histórico inteiro fica nas mensagens).
create table if not exists public.whatsapp_threads (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  number_id uuid not null references public.whatsapp_numbers(id) on delete cascade,
  wa_id text not null check (wa_id ~ '^[0-9]{6,20}$'),
  phone_key text not null check (phone_key ~ '^[0-9a-f]{32}$'),
  profile_name text,
  first_seen_at timestamptz not null default now(),
  last_message_at timestamptz not null default now(),
  last_inbound_at timestamptz,
  last_preview text,
  last_direction text check (last_direction in ('in', 'out')),
  unread_count integer not null default 0 check (unread_count >= 0),
  created_at timestamptz not null default now(),
  unique (number_id, wa_id)
);
create index if not exists whatsapp_threads_client_last_idx on public.whatsapp_threads (client_id, last_message_at desc);
create index if not exists whatsapp_threads_client_first_idx on public.whatsapp_threads (client_id, first_seen_at, id);

create table if not exists public.whatsapp_messages (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  thread_id uuid not null references public.whatsapp_threads(id) on delete cascade,
  number_id uuid not null references public.whatsapp_numbers(id) on delete cascade,
  provider_message_id text not null,
  direction text not null check (direction in ('in', 'out')),
  type text not null default 'text',
  text text check (text is null or length(text) <= 4096),
  status text not null default 'received' check (status in ('received', 'sent', 'delivered', 'read', 'failed')),
  error_code text,
  sent_at timestamptz not null default now(),
  read_at timestamptz,
  created_at timestamptz not null default now(),
  unique (number_id, provider_message_id)
);
create index if not exists whatsapp_messages_thread_idx on public.whatsapp_messages (thread_id, sent_at desc);

create table if not exists public.whatsapp_origin_touches (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  thread_id uuid not null references public.whatsapp_threads(id) on delete cascade,
  provider_message_id text not null,
  source text not null,
  referral_source_type text,
  ad_id text check (ad_id is null or ad_id ~ '^[0-9]{1,30}$'),
  ctwa_clid text,
  source_url text,
  headline text,
  body text,
  media_type text,
  entry_code text check (entry_code is null or entry_code ~ '^[a-z][a-z0-9_-]{1,39}$'),
  occurred_at timestamptz not null default now(),
  unique (thread_id, provider_message_id)
);
create index if not exists whatsapp_origin_touches_thread_idx on public.whatsapp_origin_touches (client_id, thread_id, occurred_at);

-- Recebe uma mensagem de cliente de forma atômica. A MENSAGEM entra primeiro: se ela já existe (a Meta
-- reenvia, inclusive duas vezes ao mesmo tempo), nada mais muda — a conversa não conta "não lida" em dobro.
-- A conversa é sempre da empresa dona do número; se não for (não deveria acontecer), nada é gravado.
create or replace function public.whatsapp_receive_v1(
  p_number_id uuid, p_wa_id text, p_phone_key text, p_profile_name text,
  p_provider_message_id text, p_type text, p_text text, p_sent_at timestamptz
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_client text; v_thread uuid; v_thread_client text; v_message uuid;
begin
  select client_id into v_client from public.whatsapp_numbers where id = p_number_id and status = 'active';
  if v_client is null then return jsonb_build_object('status', 'unknown_number'); end if;

  insert into public.whatsapp_threads (client_id, number_id, wa_id, phone_key, profile_name, first_seen_at, last_message_at)
    values (v_client, p_number_id, p_wa_id, p_phone_key, nullif(left(p_profile_name, 120), ''), p_sent_at, p_sent_at)
    on conflict (number_id, wa_id) do nothing;
  select id, client_id into v_thread, v_thread_client from public.whatsapp_threads where number_id = p_number_id and wa_id = p_wa_id;
  if v_thread_client is distinct from v_client then
    return jsonb_build_object('status', 'tenant_mismatch');
  end if;

  insert into public.whatsapp_messages (client_id, thread_id, number_id, provider_message_id, direction, type, text, status, sent_at)
    values (v_client, v_thread, p_number_id, p_provider_message_id, 'in', left(coalesce(p_type, 'text'), 40), left(p_text, 4096), 'received', p_sent_at)
    on conflict (number_id, provider_message_id) do nothing
    returning id into v_message;
  if v_message is null then return jsonb_build_object('status', 'duplicate', 'thread_id', v_thread); end if;

  update public.whatsapp_threads t set
    profile_name = coalesce(nullif(left(p_profile_name, 120), ''), t.profile_name),
    first_seen_at = least(t.first_seen_at, p_sent_at),
    last_message_at = greatest(t.last_message_at, p_sent_at),
    last_inbound_at = greatest(coalesce(t.last_inbound_at, p_sent_at), p_sent_at),
    last_preview = case when p_sent_at >= t.last_message_at then left(p_text, 140) else t.last_preview end,
    last_direction = case when p_sent_at >= t.last_message_at then 'in' else t.last_direction end,
    unread_count = t.unread_count + 1
  where t.id = v_thread;
  return jsonb_build_object('status', 'ok', 'thread_id', v_thread, 'client_id', v_client, 'message_id', v_message);
end $$;
revoke all on function public.whatsapp_receive_v1(uuid, text, text, text, text, text, text, timestamptz) from public, anon, authenticated;
grant execute on function public.whatsapp_receive_v1(uuid, text, text, text, text, text, text, timestamptz) to service_role;

alter table public.whatsapp_numbers enable row level security;
alter table public.whatsapp_threads enable row level security;
alter table public.whatsapp_messages enable row level security;
alter table public.whatsapp_origin_touches enable row level security;
revoke all on public.whatsapp_numbers, public.whatsapp_threads, public.whatsapp_messages, public.whatsapp_origin_touches from anon, authenticated;
grant all on public.whatsapp_numbers, public.whatsapp_threads, public.whatsapp_messages, public.whatsapp_origin_touches to service_role;

notify pgrst, 'reload schema';
