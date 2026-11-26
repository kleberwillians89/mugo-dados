-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva (reversão no fim do arquivo).
-- "A Mugô IA notou": alertas do Início calculados por regras fixas (job mugo-notices, de hora em hora).
-- mugo_notices: o que vale agora por empresa (resolved_at preenchido quando parou de valer).
-- mugo_notice_dismissals: quem dispensou e em que nível; o alerta só volta se o nível subir (piorou).
-- Só o backend (service_role) lê e grava; a API filtra por empresa e papel de quem vê.
create table if not exists public.mugo_notices (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  key text not null check (char_length(key) between 1 and 160),
  kind text not null check (kind in ('custo_subindo', 'aprovacao_parada', 'publicacao_falhou', 'data_com_rascunho',
                                     'integracao_caida', 'conta_sem_saldo')),
  level integer not null default 1 check (level >= 1),
  urgency integer not null default 0,
  message text not null check (char_length(message) <= 600),
  actions jsonb not null default '[]'::jsonb,
  data jsonb not null default '{}'::jsonb,
  client_visible boolean not null default false,
  urgent boolean not null default false,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  resolved_at timestamptz,
  whatsapp_level integer not null default 0,
  whatsapp_sent_at timestamptz,
  unique (client_id, key)
);
create index if not exists mugo_notices_open_idx on public.mugo_notices (client_id, urgency desc) where resolved_at is null;
alter table public.mugo_notices enable row level security;
revoke all on public.mugo_notices from anon, authenticated;
grant all on public.mugo_notices to service_role;

create table if not exists public.mugo_notice_dismissals (
  client_id text not null references public.clients(id) on delete cascade,
  notice_key text not null check (char_length(notice_key) between 1 and 160),
  user_id uuid not null,
  level integer not null default 1,
  dismissed_at timestamptz not null default now(),
  primary key (client_id, notice_key, user_id)
);
create index if not exists mugo_notice_dismissals_user_idx on public.mugo_notice_dismissals (user_id);
alter table public.mugo_notice_dismissals enable row level security;
revoke all on public.mugo_notice_dismissals from anon, authenticated;
grant all on public.mugo_notice_dismissals to service_role;
notify pgrst, 'reload schema';

-- Reversão:
-- drop table if exists public.mugo_notice_dismissals;
-- drop table if exists public.mugo_notices;
