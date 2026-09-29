-- Exclusao permanente e transacional de uma empresa pelo platform_admin.
--
-- POLITICA:
-- - remove somente dados vinculados ao client_id informado;
-- - remove memberships e invitations do tenant, sem excluir auth.users (um
--   usuario pode pertencer a outras empresas);
-- - remove auditorias antigas vinculadas ao tenant e preserva um evento final
--   sem e-mail, token ou credencial;
-- - a RPC e exclusiva do service_role e revalida platform_admin no banco.
--
-- MIGRATION LOCAL — nao aplicar em producao nesta entrega.

create or replace function public.delete_platform_company(
  p_actor_user_id uuid,
  p_client_id text,
  p_confirmation_name text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_client public.clients%rowtype;
  v_expected_name text;
  v_memberships_deleted bigint := 0;
  v_invitations_deleted bigint := 0;
begin
  if not public.is_platform_admin(p_actor_user_id) then
    raise exception 'platform_admin_required' using errcode = '42501';
  end if;

  if nullif(trim(coalesce(p_client_id, '')), '') is null then
    raise exception 'company_not_found' using errcode = 'PT404';
  end if;

  select * into v_client
  from public.clients
  where id = p_client_id
  for update;

  if v_client.id is null then
    raise exception 'company_not_found' using errcode = 'PT404';
  end if;

  v_expected_name := coalesce(nullif(trim(v_client.trade_name), ''), trim(v_client.name));
  if trim(coalesce(p_confirmation_name, '')) <> v_expected_name then
    raise exception 'company_name_confirmation_mismatch' using errcode = '22023';
  end if;

  -- Filas e entidades filhas sem client_id proprio.
  delete from public.meta_ads_backfill_slices
  where backfill_job_id in (
    select id from public.meta_ads_backfill_jobs where client_id = p_client_id
  );
  delete from public.meta_ads_backfill_jobs where client_id = p_client_id;

  -- Inteligencia e conversas.
  delete from public.ai_messages where client_id = p_client_id;
  delete from public.ai_conversations where client_id = p_client_id;
  delete from public.ai_analyses where client_id = p_client_id;

  -- Read models e metricas importadas.
  delete from public.dashboard_product_metrics where client_id = p_client_id;
  delete from public.dashboard_campaign_metrics where client_id = p_client_id;
  delete from public.dashboard_daily_metrics where client_id = p_client_id;
  delete from public.dashboard_source_snapshots where client_id = p_client_id;
  delete from public.google_ads_daily_stats where client_id = p_client_id;
  delete from public.ga4_landing_page_stats where client_id = p_client_id;
  delete from public.ga4_event_stats where client_id = p_client_id;
  delete from public.ga4_campaign_stats where client_id = p_client_id;
  delete from public.ga4_channel_stats where client_id = p_client_id;
  delete from public.ga4_daily_stats where client_id = p_client_id;
  delete from public.promoted_post_daily_stats where client_id = p_client_id;
  delete from public.ad_daily_stats where client_id = p_client_id;
  delete from public.campaign_daily_stats where client_id = p_client_id;
  delete from public.ad_account_daily_stats where client_id = p_client_id;
  delete from public.ig_comments where client_id = p_client_id;
  delete from public.ig_media where client_id = p_client_id;
  delete from public.ig_profile_snapshots where client_id = p_client_id;
  delete from public.fbits_order_items where client_id = p_client_id;
  delete from public.fbits_orders where client_id = p_client_id;
  delete from public.fbits_order_daily_stats where client_id = p_client_id;
  delete from public.shopify_order_items where client_id = p_client_id;
  delete from public.shopify_refunds where client_id = p_client_id;
  delete from public.shopify_orders where client_id = p_client_id;
  delete from public.shopify_customers where client_id = p_client_id;
  delete from public.shopify_webhook_events where client_id = p_client_id;

  -- Estado operacional, OAuth e conexoes.
  delete from public.sync_checkpoints where client_id = p_client_id;
  delete from public.connection_audit_events where client_id = p_client_id;
  delete from public.shopify_stores where client_id = p_client_id;
  delete from public.oauth_sessions where client_id = p_client_id;
  delete from public.meta_oauth_handoffs where client_id = p_client_id;
  delete from public.cron_job_runs where client_id = p_client_id;
  delete from public.cron_locks where client_id = p_client_id;
  delete from public.meta_token_events where client_id = p_client_id;
  delete from public.client_notes where client_id = p_client_id;
  delete from public.integration_connections where client_id = p_client_id;
  delete from public.meta_connections where client_id = p_client_id;

  -- Acessos e convites do tenant. auth.users nao e excluida.
  delete from public.user_invitations where client_id = p_client_id;
  get diagnostics v_invitations_deleted = row_count;
  delete from public.client_memberships where client_id = p_client_id;
  get diagnostics v_memberships_deleted = row_count;
  -- A migration 001 reconhece esta tabela apenas quando existe em bases
  -- legadas. SQL dinamico evita depender dela em instalacoes novas.
  if to_regclass('public.client_users') is not null then
    execute 'delete from public.client_users where client_id::text = $1'
      using p_client_id;
  end if;

  -- Auditorias antigas podem conter contexto da empresa removida. O evento
  -- final e desacoplado do FK e registra apenas metadados nao secretos.
  delete from public.platform_audit_events where client_id = p_client_id;
  delete from public.clients where id = p_client_id;

  insert into public.platform_audit_events(actor_user_id, client_id, event_type, details)
  values (
    p_actor_user_id,
    null,
    'company_permanently_deleted',
    jsonb_build_object(
      'deleted_client_id', v_client.id,
      'deleted_company_name', v_expected_name,
      'memberships_deleted', v_memberships_deleted,
      'invitations_deleted', v_invitations_deleted
    )
  );

  return jsonb_build_object(
    'deleted_client_id', v_client.id,
    'deleted_company_name', v_expected_name,
    'memberships_deleted', v_memberships_deleted,
    'invitations_deleted', v_invitations_deleted
  );
end;
$$;

revoke all on function public.delete_platform_company(uuid,text,text)
  from public, anon, authenticated;
grant execute on function public.delete_platform_company(uuid,text,text)
  to service_role;
