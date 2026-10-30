-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Aprendizado contínuo por campanha + resumo semanal no WhatsApp.
--
-- studio_campaign_learnings: uma linha por campanha e semana (Meta Ads e
-- Google Ads), gravada toda sexta pelo job studio-weekly-digest. Guarda o
-- desempenho da semana, a média do canal, o que o Mídia On recomendou e o que
-- a equipe planejou (verba e ação do plano do mês). É a memória que o Mídia On
-- usa para aprender: campanha nova, tendência de ROAS, escala que funcionou ou
-- não, campanha que parou.
--
-- studio_messages: novo tipo "semanal" (resumo de sexta) e status "aguardando"
-- (MugôZap ainda não configurado ou cliente sem número): a mensagem fica
-- registrada e passa a sair sozinha quando o WhatsApp for ligado.

create table if not exists public.studio_campaign_learnings (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  channel text not null check (channel in ('meta', 'google_ads')),
  campaign_key text not null check (length(campaign_key) between 1 and 200),
  campaign_name text not null check (length(campaign_name) between 1 and 200),
  week_start date not null,
  week_end date not null,
  first_seen date not null,
  spend numeric(14, 2) not null default 0,
  impressions numeric(16, 0) not null default 0,
  clicks numeric(14, 0) not null default 0,
  conversions numeric(12, 2) not null default 0,
  revenue numeric(14, 2) not null default 0,
  roas numeric(10, 4),
  cpa numeric(14, 4),
  channel_roas numeric(10, 4),
  channel_cpa numeric(14, 4),
  recommended_action text check (recommended_action is null or length(recommended_action) <= 20),
  planned_action text check (planned_action is null or length(planned_action) <= 20),
  planned_budget numeric(14, 2),
  note text check (note is null or length(note) <= 500),
  created_at timestamptz not null default now(),
  unique (client_id, channel, campaign_key, week_start)
);

create index if not exists studio_campaign_learnings_client_idx
  on public.studio_campaign_learnings (client_id, week_start desc);

alter table public.studio_campaign_learnings enable row level security;
revoke all on public.studio_campaign_learnings from anon, authenticated;
grant select on public.studio_campaign_learnings to authenticated;
grant all on public.studio_campaign_learnings to service_role;
drop policy if exists studio_campaign_learnings_member_read on public.studio_campaign_learnings;
create policy studio_campaign_learnings_member_read on public.studio_campaign_learnings
  for select to authenticated using (public.is_client_member(client_id));

alter table public.studio_messages drop constraint if exists studio_messages_kind_check;
alter table public.studio_messages add constraint studio_messages_kind_check
  check (kind in ('aprovacao', 'lembrete', 'agenda', 'trafego', 'resultados', 'semanal'));
alter table public.studio_messages drop constraint if exists studio_messages_status_check;
alter table public.studio_messages add constraint studio_messages_status_check
  check (status in ('enviado', 'falhou', 'link_gerado', 'aguardando'));

notify pgrst, 'reload schema';
