-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Seguidores online por hora (métrica online_followers do Instagram).
-- A Meta só devolve os últimos 30 dias e só para contas com 100+ seguidores,
-- por isso o sync orgânico grava um dia por linha e o histórico se acumula aqui.
--
-- hour_key é a hora exatamente como a Meta devolve (0..23). O fuso dessa hora
-- não é documentado pela Meta; a conversão para São Paulo acontece na leitura
-- (services/posting_times.py), nunca na gravação, para não perder o dado bruto.
create table if not exists public.ig_online_followers (
  id bigserial primary key,
  client_id text not null,
  connection_id uuid,
  metric_date date not null,
  end_time timestamptz,
  hour_key smallint not null check (hour_key between 0 and 23),
  followers_online integer not null default 0 check (followers_online >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, metric_date, hour_key)
);

create index if not exists ig_online_followers_client_date_idx
  on public.ig_online_followers (client_id, metric_date);

alter table public.ig_online_followers enable row level security;
revoke all on public.ig_online_followers from anon, authenticated;
grant select on public.ig_online_followers to authenticated;
grant all on public.ig_online_followers to service_role;
grant usage, select on sequence public.ig_online_followers_id_seq to service_role;

drop policy if exists ig_online_followers_member_read on public.ig_online_followers;
create policy ig_online_followers_member_read on public.ig_online_followers
  for select to authenticated using (public.is_client_member(client_id));
-- Nenhuma escrita pelo browser: só o sync (service_role) grava.

drop trigger if exists ig_online_followers_updated_at on public.ig_online_followers;
create trigger ig_online_followers_updated_at before update on public.ig_online_followers
  for each row execute function public.set_updated_at();

notify pgrst, 'reload schema';
