# Exclusão permanente de empresa

A exclusão permanente é diferente da inativação reversível. Ela está disponível somente para `platform_admin`, exige confirmação literal do nome e é executada no backend pela RPC transacional `delete_platform_company`.

## Política de identidade e acesso

- o `client_id` excluído vem exclusivamente do path da API;
- `viewer`, `client_admin` e `agency_admin` não podem executar a operação;
- memberships e convites do tenant são removidos;
- usuários do Supabase Auth não são excluídos, pois podem pertencer a outros tenants;
- a empresa atualmente aberta deve ser trocada antes da exclusão;
- a auditoria final não registra e-mail, token, senha, chave ou credencial.

## Relações mapeadas

A migration cobre as relações tenant-scoped presentes nas migrations anteriores:

- acesso: `client_memberships`, `user_invitations` e a tabela legada opcional `client_users`;
- OAuth e conexões: `meta_connections`, `integration_connections`, `oauth_sessions`, `meta_oauth_handoffs`, `shopify_stores`;
- operação e auditoria: `connection_audit_events`, `platform_audit_events`, `sync_checkpoints`, `cron_job_runs`, `cron_locks`, `meta_token_events`, `client_notes`;
- Meta e Instagram: `ad_account_daily_stats`, `campaign_daily_stats`, `ad_daily_stats`, `promoted_post_daily_stats`, `ig_comments`, `ig_media`, `ig_profile_snapshots`, `meta_ads_backfill_jobs` e suas slices;
- Google: `ga4_daily_stats`, `ga4_channel_stats`, `ga4_campaign_stats`, `ga4_event_stats`, `ga4_landing_page_stats`, `google_ads_daily_stats`;
- comércio: `shopify_webhook_events`, `shopify_orders`, `shopify_order_items`, `shopify_customers`, `shopify_refunds`, `fbits_order_daily_stats`, `fbits_orders`, `fbits_order_items`;
- inteligência: `ai_analyses`, `ai_conversations`, `ai_messages`;
- read models: `dashboard_daily_metrics`, `dashboard_campaign_metrics`, `dashboard_product_metrics`, `dashboard_source_snapshots`.

`meta_ads_backfill_slices` não possui `client_id`; ela é removida pelo vínculo com `meta_ads_backfill_jobs` antes da exclusão do job.

`client_users` não é criada pelas migrations atuais, mas a migration inicial reconhece essa tabela em bases legadas. A RPC a limpa condicionalmente por `client_id` para evitar vínculo órfão ou eventual bloqueio por FK.

## Pendência operacional

A migration `20260929_000036_platform_company_permanent_deletion.sql` foi criada somente no repositório. Ela precisa ser revisada e aplicada pelo processo controlado de migrations antes que o endpoint seja usado em produção. Esta entrega não aplica migration nem altera banco remoto.
