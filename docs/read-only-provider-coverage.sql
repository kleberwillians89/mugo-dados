-- NÃO executado pelo agente. Somente SELECT; executar no SQL Editor do Supabase.
-- 1. Conferir as tabelas. Se faltar alguma, não interpretar erro como "sem dados".
SELECT x.table_name, to_regclass('public.' || x.table_name) IS NOT NULL AS exists
FROM (VALUES ('clients'), ('ig_profile_snapshots'), ('ad_account_daily_stats'),
             ('google_ads_daily_stats'), ('ga4_daily_stats'), ('ga4_channel_stats'),
             ('ga4_campaign_stats'), ('ga4_event_stats'), ('dashboard_source_snapshots'),
             ('meta_connections'), ('integration_connections')) AS x(table_name);

-- 2. Conferir os tenants localizados. Só Curavino tem UUID confirmado.
-- Os padrões podem localizar mais de uma empresa: confirmar IDs antes da atribuição.
SELECT id AS client_id, name AS tenant FROM public.clients
WHERE id = '239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94'
   OR name ILIKE '%roove%' OR name ILIKE '%origami%'
   OR name ILIKE '%ruah%' OR name ILIKE '%mug%'
ORDER BY name, id;

-- 3. Cobertura POR ESCOPO. Não soma contas/propriedades para completar 90 datas.
-- last_projection_success_at é metadado tenant/provider, não certificado por escopo.
-- source_last_sync_at é metadado operacional da conexão, não prova completeness.
WITH
date_bounds AS (
  SELECT (now() AT TIME ZONE 'America/Sao_Paulo')::date AS end_date,
         (now() AT TIME ZONE 'America/Sao_Paulo')::date - 89 AS start_date
),
requested(tenant, name_pattern, explicit_id) AS (
  VALUES ('Curavino', '%curavino%', '239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94'),
         ('Roove', '%roove%', NULL), ('Origami', '%origami%', NULL),
         ('Ruah', '%ruah%', NULL), ('Mugô', '%mug%', NULL)
),
targets AS (
  SELECT r.tenant, c.id AS client_id, c.name AS registered_company_name
  FROM requested r LEFT JOIN public.clients c
    ON CASE WHEN r.explicit_id IS NOT NULL THEN c.id = r.explicit_id
            ELSE c.name ILIKE r.name_pattern END
),
datasets(provider, dataset) AS (
  VALUES ('instagram', 'ig_profile_snapshots'), ('meta', 'ad_account_daily_stats'),
         ('google_ads', 'google_ads_daily_stats'), ('ga4', 'ga4_daily_stats'),
         ('ga4', 'ga4_channel_stats'), ('ga4', 'ga4_campaign_stats'), ('ga4', 'ga4_event_stats')
),
facts AS (
  SELECT s.client_id, 'ig_profile_snapshots'::text AS dataset,
         s.connection_id::text AS connection_id, NULL::text AS account_property,
         s.snapshot_date AS fact_date, s.updated_at
  FROM public.ig_profile_snapshots s WHERE s.client_id IN (SELECT client_id FROM targets)
  UNION ALL
  SELECT s.client_id, 'ad_account_daily_stats',
         coalesce(to_jsonb(s)->>'meta_connection_id', s.connection_id::text),
         s.ad_account_id, s.stat_date, s.updated_at
  FROM public.ad_account_daily_stats s WHERE s.client_id IN (SELECT client_id FROM targets)
  UNION ALL
  SELECT s.client_id, 'google_ads_daily_stats', s.connection_id::text,
         s.customer_id, s.stat_date, s.updated_at
  FROM public.google_ads_daily_stats s WHERE s.client_id IN (SELECT client_id FROM targets)
  UNION ALL
  SELECT s.client_id, 'ga4_daily_stats', NULL, s.property_id, s.stat_date, s.updated_at
  FROM public.ga4_daily_stats s WHERE s.client_id IN (SELECT client_id FROM targets)
  UNION ALL
  SELECT s.client_id, 'ga4_channel_stats', NULL, s.property_id, s.stat_date, s.updated_at
  FROM public.ga4_channel_stats s WHERE s.client_id IN (SELECT client_id FROM targets)
  UNION ALL
  SELECT s.client_id, 'ga4_campaign_stats', NULL, s.property_id, s.stat_date, s.updated_at
  FROM public.ga4_campaign_stats s WHERE s.client_id IN (SELECT client_id FROM targets)
  UNION ALL
  SELECT s.client_id, 'ga4_event_stats', NULL, s.property_id, s.stat_date, s.updated_at
  FROM public.ga4_event_stats s WHERE s.client_id IN (SELECT client_id FROM targets)
),
coverage AS (
  SELECT f.client_id, f.dataset, f.connection_id, f.account_property,
         min(f.fact_date) AS min_date, max(f.fact_date) AS max_date,
         count(DISTINCT f.fact_date) AS distinct_dates, count(*) AS row_count,
         count(DISTINCT f.fact_date) FILTER
           (WHERE f.fact_date BETWEEN w.start_date AND w.end_date) AS distinct_dates_in_window,
         max(f.updated_at) AS last_fact_persisted_at
  FROM facts f CROSS JOIN date_bounds w
  GROUP BY f.client_id, f.dataset, f.connection_id, f.account_property
)
SELECT t.tenant, t.client_id, t.registered_company_name,
       t.client_id IS NOT NULL AS tenant_found, d.provider, d.dataset,
       a.connection_id, a.account_property, a.min_date, a.max_date,
       coalesce(a.distinct_dates, 0) AS distinct_dates,
       coalesce(a.distinct_dates_in_window, 0) AS distinct_dates_in_window,
       coalesce(a.row_count, 0) AS row_count, a.last_fact_persisted_at,
       ss.last_success_at AS last_projection_success_at,
       source.source_last_sync_at,
       w.start_date, w.end_date,
       CASE WHEN t.client_id IS NULL THEN 'tenant nao localizado: confirmar UUID'
            WHEN coalesce(a.row_count, 0) = 0 THEN 'sem dados'
            WHEN a.distinct_dates_in_window = 90 THEN '90 datas persistidas'
            ELSE 'parcial' END AS coverage_status,
       'NAO CONFIRMADA: requer coleta completa e reconciliacao da origem' AS completeness_status,
       CASE WHEN d.provider = 'instagram' THEN 'observacoes; nao prova atividade historica diaria'
            WHEN d.provider = 'ga4' THEN 'usuarios nao aditivos entre dias/dimensoes'
            WHEN d.provider = 'meta' THEN 'alcance nao aditivo entre dias/entidades'
            ELSE 'fatos diarios; verificar escopos e entidades removidas' END AS semantics
FROM targets t CROSS JOIN datasets d CROSS JOIN date_bounds w
LEFT JOIN coverage a ON a.client_id = t.client_id AND a.dataset = d.dataset
LEFT JOIN public.dashboard_source_snapshots ss ON ss.client_id = t.client_id AND ss.provider = d.provider
LEFT JOIN LATERAL (
  SELECT max(s.source_last_sync_at) AS source_last_sync_at
  FROM (
    SELECT c.last_sync_at AS source_last_sync_at
    FROM public.integration_connections c
    WHERE c.client_id = t.client_id AND c.provider = d.provider
      AND ((d.provider = 'ga4' AND replace(c.metadata->>'ga4_property_id', 'properties/', '') = a.account_property)
           OR (d.provider <> 'ga4' AND c.id::text = a.connection_id))
    UNION ALL
    SELECT coalesce(c.last_synced_at, CASE WHEN c.last_sync_status = 'success' THEN c.last_sync_at END)
    FROM public.meta_connections c
    WHERE d.provider IN ('instagram', 'meta') AND c.client_id = t.client_id
      AND c.id::text = a.connection_id
  ) s
) source ON true
ORDER BY t.tenant, t.client_id, d.provider, d.dataset, a.account_property, a.connection_id;

-- Não retorna nome de pessoa, contato, token, erro bruto, headers ou payloads.
-- Ausência de fatos não prova "não aplicável"; confirmar conexão e necessidade comercial.
-- Não usa 90 datas como selo de completude. Não executa sync/backfill/reprojection.
