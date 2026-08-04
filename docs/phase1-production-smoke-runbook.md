# Mugô Dados — Fase 1: auditoria e smoke tests de produção

Este runbook não faz deploy, não altera secrets e não autoriza correções automáticas. Os passos de `POST` representam ações explícitas de teste e só devem ser executados em janela aprovada. As consultas SQL são somente leitura e nunca selecionam colunas de token.

## Preparação segura

```bash
export MUGO_API_BASE="https://api.dados.mugoagencia.com.br"
export MUGO_ACCESS_TOKEN="<JWT de agency_admin>"
export MUGO_CLIENT_ID="amalie"
export META_CONNECTION_ID="<UUID Meta validado>"
export GA4_CONNECTION_ID="<UUID GA4 validado>"
export SHOPIFY_CONNECTION_ID="<UUID Shopify validado>"
```

Para auditoria Supabase, usar preferencialmente `SUPABASE_AUDIT_KEY`, pertencente a uma role/view com `SELECT` apenas. `SUPABASE_SERVICE_ROLE_KEY` é aceito como fallback operacional, mas tem privilégios excessivos e deve ser usado somente em ambiente controlado.

A credencial restrita precisa de `SELECT` em `integration_connections`, `meta_connections`, `sync_checkpoints`, `shopify_stores`, `cron_job_runs` e nas tabelas de métricas referenciadas pelo relatório. Se ela não puder ler campos criptografados, configure `SUPABASE_AUDIT_CONNECTIONS_RESOURCE` para uma view somente leitura que exponha apenas os campos não secretos mais `token_available boolean` e `refresh_token_available boolean`. O script não descriptografa credenciais.

As únicas requisições remotas emitidas são `GET /rest/v1/<recurso>?select=...` e `GET /rest/v1/` para o catálogo OpenAPI. Não existem métodos de insert, update ou delete no cliente de auditoria.

```bash
python3 server/scripts/audit_connections.py
python3 server/scripts/audit_locks.py
```

Arquivos esperados: `audit-output/audit-report.json`, `audit-output/audit-report.csv` e `audit-output/lock-infrastructure-report.json`. O transporte dos scripts aceita somente HTTP `GET`.

Para confirmar constraint, índices e privilégios diretamente no PostgreSQL, executar `server/sql/audit_locks_readonly.sql`. O arquivo contém exclusivamente `SELECT` e consulta `pg_proc`, `pg_constraint`, `pg_indexes` e privilégios da role atual; ele não chama as RPCs de lock.

## Meta — Amalie

| Passo | Endpoint/ação | Resultado esperado | Tabela consultada | Erro possível | Ação corretiva |
|---|---|---|---|---|---|
| 1 | `GET /api/connections?client_id=amalie` | Uma autorização `meta` ativa e não desconectada | `integration_connections` | `CONNECTION_AMBIGUOUS` | Auditar duplicidades; não escolher automaticamente |
| 2 | `POST /api/oauth/meta/$META_CONNECTION_ID/manual-assets/validate?client_id=amalie` com `page_id`, `instagram_id` e Ads opcional | `ok=true`; IDs pertencem ao token e Página/Instagram correspondem | nenhuma escrita; leitura Graph | `META_PAGE_INSTAGRAM_MISMATCH`, `META_PERMISSION_MISSING`, `META_REAUTH_REQUIRED` | Corrigir IDs/permissões ou reautorizar explicitamente |
| 3 | `POST /api/oauth/meta/$META_CONNECTION_ID/manual-assets?client_id=amalie` com o mesmo payload | Ativos salvos; `initial_sync.ok=true` ou falha explícita preservando ativos | `integration_connections`, `meta_connections` | `META_CONNECTION_DRIFT`, `META_GRAPH_UNAVAILABLE` | Inspecionar health; retry manual sem apagar ativos |
| 4 | `POST /api/ig/sync?client_id=amalie&connection_id=<organic_uuid>&limit=40` | Sync concluída ou `409 SYNC_ALREADY_RUNNING` | `cron_locks`, `cron_job_runs`, tabelas `ig_*` | `META_REAUTH_REQUIRED`, `SYNC_ALREADY_RUNNING` | Reautorizar ou aguardar TTL/execução atual |
| 5 | `GET /api/admin/health/clients/amalie/providers/meta` | `drift_detected=false`, token e ativos válidos | conexões e runs | `META_CONNECTION_DRIFT` | Parar; não reparar silenciosamente |
| 6 | Sair, entrar e abrir o dashboard | Snapshot reaparece antes do refresh; IDs permanecem iguais | `ig_profile_snapshots`, `ig_media`, `ig_comments` | dashboard vazio com snapshots existentes | Conferir tenant/cache key e request IDs |

Consultas somente leitura:

```sql
select id, client_id, provider, status, account_id, disconnected_at, metadata, last_sync_at
from integration_connections where client_id = 'amalie' and provider = 'meta';

select id, client_id, platform, connection_type, status, is_active,
       ig_user_id, business_id, ad_account_id, last_sync_at, last_error
from meta_connections where client_id = 'amalie';

select client_id, connection_id, snapshot_date, followers_count, reach, impressions
from ig_profile_snapshots where client_id = 'amalie'
order by snapshot_date desc limit 10;
```

## GA4

| Passo | Endpoint/ação | Resultado esperado | Tabela consultada | Erro possível | Ação corretiva |
|---|---|---|---|---|---|
| 1 | `GET /api/connections?client_id=amalie` | Exatamente uma conexão GA4 utilizável | `integration_connections` | `CONNECTION_AMBIGUOUS`, `CONNECTION_DISCONNECTED` | Resolver duplicidade ou conectar explicitamente |
| 2 | `GET /api/oauth/google/$GA4_CONNECTION_ID/ga4/properties?client_id=amalie` | Lista de propriedades; refresh transparente se necessário | `integration_connections`; Analytics Admin API | `GOOGLE_REAUTH_REQUIRED_INVALID_GRANT`, `GOOGLE_ADMIN_API_DISABLED` | Reautorizar ou habilitar Admin API |
| 3 | `GET /api/oauth/google/$GA4_CONNECTION_ID/ga4/streams?client_id=amalie&property_id=<property>` | Streams acessíveis da propriedade | Analytics Admin API | `GOOGLE_STREAM_UNAVAILABLE` | Selecionar propriedade/stream acessível |
| 4 | `POST /api/oauth/google/$GA4_CONNECTION_ID/ga4/select?client_id=amalie` com `property_id` e `stream_id` | Metadata da conexão mantém property e stream | `integration_connections` | `GOOGLE_PROPERTY_UNAVAILABLE`, `GOOGLE_STREAM_UNAVAILABLE` | Repetir descoberta; não reiniciar OAuth automaticamente |
| 5 | `POST /api/oauth/google/$GA4_CONNECTION_ID/sync?client_id=amalie&days=30` | `ok=true`, run concluída e linhas persistidas | `cron_locks`, `cron_job_runs`, `ga4_*` | `GOOGLE_DATA_API_DISABLED`, `SYNC_ALREADY_RUNNING` | Habilitar Data API ou aguardar lock |
| 6 | Sair, entrar e abrir Google Analytics/dashboard | Propriedade selecionada e snapshots reaparecem | `integration_connections`, `ga4_daily_stats`, `ga4_landing_page_stats` | seleção perdida | Conferir metadata e tenant do callback |

```sql
select id, client_id, provider, status, account_id, token_expires_at,
       disconnected_at, metadata, scopes, last_sync_at
from integration_connections where client_id = 'amalie' and provider = 'ga4';

select client_id, property_id, stat_date, sessions, active_users, total_users,
       event_count, transactions, purchase_revenue
from ga4_daily_stats where client_id = 'amalie'
order by stat_date desc limit 31;

select client_id, property_id, stat_date, landing_page, sessions, active_users
from ga4_landing_page_stats where client_id = 'amalie'
order by stat_date desc limit 31;
```

## Shopify

| Passo | Endpoint/ação | Resultado esperado | Tabela consultada | Erro possível | Ação corretiva |
|---|---|---|---|---|---|
| 1 | Concluir OAuth por ação explícita e `POST /api/oauth/shopify/$SHOPIFY_CONNECTION_ID/select?client_id=<tenant>` | Loja marcada para reporting, sem ambiguidade | `integration_connections`, `shopify_stores` | `SHOPIFY_STORE_SELECTION_REQUIRED`, `SHOPIFY_REAUTH_REQUIRED` | Selecionar uma loja ou reautorizar |
| 2 | `POST /api/oauth/shopify/$SHOPIFY_CONNECTION_ID/sync?client_id=<tenant>&days=30` | Pedidos importados e checkpoint atualizado | `shopify_orders`, `shopify_order_items`, `sync_checkpoints`, `cron_job_runs` | rate limit ou token revogado | Retry controlado; preservar snapshot existente |
| 3 | Reenviar duas vezes o mesmo webhook válido, com mesmo `X-Shopify-Webhook-Id` e corpo | Um único evento lógico; segunda entrega não duplica pedido | `shopify_webhook_events`, `shopify_orders` | HMAC inválido | Usar redelivery oficial/assinatura válida; nunca expor secret |
| 4 | `GET /api/shopify/report?client_id=<tenant>&start=<date>&end=<date>` | Dashboard mostra pedidos persistidos | tabelas Shopify | `SHOPIFY_CONNECTION_NOT_FOUND` | Conferir seleção explícita e domínio |
| 5 | Trocar tenant e repetir report | Nenhum pedido da loja anterior aparece | `client_id` em todas as tabelas Shopify | vazamento cruzado | Bloquear lançamento e registrar request IDs |
| 6 | Sair/entrar | Último snapshot reaparece | tabelas Shopify e cache tenant-scoped | dashboard zerado em falha temporária | Conferir reidratação e TTL |

```sql
select id, client_id, connection_id, shop_domain, status, uninstalled_at
from shopify_stores order by client_id, shop_domain;

select client_id, webhook_id, topic, status, count(*)
from shopify_webhook_events
group by client_id, webhook_id, topic, status
having count(*) > 1;

select client_id, shopify_order_id, updated_at_shopify
from shopify_orders where client_id = '<tenant>'
order by updated_at_shopify desc limit 50;
```

## Google Ads — fora do escopo desta execução

Ainda faltam evidências/implementação completa para: OAuth válido; listagem de contas; seleção de `customer_id`; manager account; `login_customer_id`; campanhas; métricas; persistência; sync incremental; dashboard; idempotência; locks; taxonomia de erros; testes unitários, concorrentes e smoke tests reais. Nenhum desses itens deve ser apresentado como concluído nesta fase.

## Critério objetivo de encerramento

1. `audit-report.json` sem `critical` não tratado.
2. Infraestrutura de locks com tabelas e RPCs visíveis, SELECT permitido e contrato SQL local íntegro.
3. Smoke Meta, GA4 e Shopify concluído com request IDs e evidências de persistência/rehidratação.
4. Zero mistura entre tenants nos testes e nas consultas reais.
5. Nenhum token ou secret presente nos artefatos de auditoria.
