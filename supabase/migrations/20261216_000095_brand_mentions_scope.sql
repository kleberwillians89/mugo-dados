-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; corrige a 000094.
-- Saúde da marca conta só o que é sobre a marca:
-- - notícia: radar da marca e dos porta-vozes (kind marca/pessoa); concorrente e tema ficam de fora;
-- - comentário: tira os que a própria conta da marca escreveu (respostas da marca no post).

create or replace view public.brand_mentions with (security_invoker = true) as
  select c.client_id, 'news'::text as source, coalesce(c.published_at, c.created_at) as at, c.sentiment, c.main_theme as theme,
         c.title as body, c.url as link
    from public.studio_clippings c
   where c.relevant is not false and c.kind in ('marca', 'pessoa')
  union all
  select m.client_id, 'comments', coalesce(m.timestamp, m.created_at), m.sentiment, m.theme, m.text, null
    from public.ig_comments m
   where not exists (
     select 1 from public.meta_connections mc
      where mc.client_id = m.client_id and mc.platform = 'instagram' and mc.username is not null
        and lower(mc.username) = lower(coalesce(m.username, '')))
  union all
  select d.client_id, 'direct', d.created_at, d.sentiment, d.theme, d.text, null
    from public.ig_dm_messages d where d.direction = 'in';

revoke all on public.brand_mentions from anon, authenticated;
grant select on public.brand_mentions to service_role;
notify pgrst, 'reload schema';
