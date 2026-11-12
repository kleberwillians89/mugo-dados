-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Saúde da marca: revisão humana dos comentários e Direct analisados pela IA.
-- A equipe abre o "!" do comentário, vê de onde veio (post, @, data) e pode
-- trocar o sentimento (duplo sentido que a IA não entendeu) ou tirar da avaliação.
-- sentiment_ai guarda o que a IA disse; sentiment passa a ser o valor revisado.

alter table public.ig_comments
  add column if not exists sentiment_ai text check (sentiment_ai is null or sentiment_ai in ('positivo', 'neutro', 'negativo', 'misto')),
  add column if not exists health_excluded boolean not null default false,
  add column if not exists reviewed_by uuid references auth.users(id) on delete set null,
  add column if not exists reviewed_at timestamptz;
alter table public.ig_dm_messages
  add column if not exists sentiment_ai text check (sentiment_ai is null or sentiment_ai in ('positivo', 'neutro', 'negativo', 'misto')),
  add column if not exists health_excluded boolean not null default false,
  add column if not exists reviewed_by uuid references auth.users(id) on delete set null,
  add column if not exists reviewed_at timestamptz;

-- Mesmas colunas e ordem da 000095; só passa a ignorar o que a equipe tirou da avaliação.
create or replace view public.brand_mentions with (security_invoker = true) as
  select c.client_id, 'news'::text as source, coalesce(c.published_at, c.created_at) as at, c.sentiment, c.main_theme as theme,
         c.title as body, c.url as link
    from public.studio_clippings c
   where c.relevant is not false and c.kind in ('marca', 'pessoa')
  union all
  select m.client_id, 'comments', coalesce(m.timestamp, m.created_at), m.sentiment, m.theme, m.text, null
    from public.ig_comments m
   where m.health_excluded is not true
     and not exists (
     select 1 from public.meta_connections mc
      where mc.client_id = m.client_id and mc.platform = 'instagram' and mc.username is not null
        and lower(mc.username) = lower(coalesce(m.username, '')))
  union all
  select d.client_id, 'direct', d.created_at, d.sentiment, d.theme, d.text, null
    from public.ig_dm_messages d where d.direction = 'in' and d.health_excluded is not true;

revoke all on public.brand_mentions from anon, authenticated;
grant select on public.brand_mentions to service_role;
notify pgrst, 'reload schema';
