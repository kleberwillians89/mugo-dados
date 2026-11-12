-- LOCAL: NÃO APLICADA (000105). Revisão/aplicação remota manual; feature aditiva.
-- Índice de saúde MUGOVERSO (Clipping → Saúde da marca): junta conversa, reputação, atenção no Instagram,
-- presença na mídia (share de voz vs concorrentes) e conversão em vendas numa nota de 0 a 100.
-- Cada empresa ajusta o peso de cada pilar (o admin do cliente também pode editar).

alter table public.brand_health_settings
  add column if not exists index_weights jsonb,
  add column if not exists weights_updated_by uuid,
  add column if not exists weights_updated_at timestamptz;

alter table public.brand_health_settings drop constraint if exists brand_health_settings_index_weights_check;
alter table public.brand_health_settings add constraint brand_health_settings_index_weights_check
  check (index_weights is null or jsonb_typeof(index_weights) = 'object');

-- Notícias do período por tipo do radar (marca/porta-voz vs concorrente) para o share de voz.
create or replace function public.brand_health_share(p_client text, p_start timestamptz, p_end timestamptz)
returns table(kind text, n bigint)
language sql stable security invoker set search_path = public as $$
  select c.kind, count(*)
    from public.studio_clippings c
   where c.client_id = p_client and c.relevant is not false
     and coalesce(c.published_at, c.created_at) >= p_start and coalesce(c.published_at, c.created_at) < p_end
     and c.kind in ('marca', 'pessoa', 'concorrente')
   group by 1
$$;

revoke execute on function public.brand_health_share(text, timestamptz, timestamptz) from public, anon, authenticated;
grant execute on function public.brand_health_share(text, timestamptz, timestamptz) to service_role;

notify pgrst, 'reload schema';
