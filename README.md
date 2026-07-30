# mugo_metrics

Painel de métricas Instagram com frontend React/Vite e backend FastAPI integrado ao Supabase.

## Arquitetura Atual
- Frontend autentica com Supabase Auth (JWT).
- Frontend chama backend com `Authorization: Bearer <jwt>`.
- Backend resolve tenant por membership (`client_memberships`) e nunca por fallback global.
- Backend usa `meta_connections` para gerenciar token Meta por cliente/conexão.
- O dashboard pago lê o último dado persistido e não depende da Meta em tempo real.
- O sync de Meta Ads faz validação de token, refresh defensivo, upsert idempotente e registra job runs.

## Setup Local
1. Instale deps do frontend:
```bash
npm install
```
2. Crie `.env` na raiz usando `.env.example` (VITE vars).
3. Crie `server/.env` com as variáveis de backend da `.env.example`.
4. Rode as migrações SQL da pasta `supabase/migrations` no Supabase.
Hoje, no mínimo, o ambiente precisa destas migrações:
```text
supabase/migrations/20260305_000001_multi_tenant_and_features.sql
supabase/migrations/20260325_000002_meta_oauth_paid_multi_asset.sql
supabase/migrations/20260408_000003_promoted_post_daily_stats.sql
supabase/migrations/20260408_000004_paid_schema_completion.sql
supabase/migrations/20260408_000005_promoted_post_daily_stats_bootstrap.sql
supabase/migrations/20260408_000006_paid_upsert_unique_indexes.sql
supabase/migrations/20260408_000007_paid_table_column_hardening.sql
supabase/migrations/20260408_000008_ig_media_connection_alignment.sql
supabase/migrations/20260416_000009_meta_oauth_handoffs.sql
supabase/migrations/20260417_000010_meta_ads_operational_stability.sql
```
5. Instale dependências do backend:
```bash
cd server
pip install -r requirements.txt
```
6. Inicie backend:
```bash
cd server
uvicorn app:app --reload --port 8000
```
7. Inicie frontend:
```bash
npm run dev
```

## Variáveis de Ambiente do Backend
Use [`server/.env.example`](server/.env.example) como base.

Obrigatórias para a operação atual de Meta Ads:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `TOKEN_ENCRYPTION_KEY`
- `META_APP_ID`
- `META_APP_SECRET`
- `CRON_SECRET`

Importantes para operação local e OAuth já existente:
- `META_OAUTH_REDIRECT_URI`
- `ALLOW_ORIGIN`
- `ALLOW_NO_AUTH`
- `DEV_USER_ID`

Opcionais para calibrar a operação:
- `META_TOKEN_REFRESH_WINDOW_DAYS` default `7`
- `META_TOKEN_VALIDATE_WINDOW_HOURS` default `6`

## Login com Meta (Supabase Auth)
Para o botão **Entrar com Meta** funcionar, configure no Supabase:
1. `Authentication -> Providers -> Facebook` (habilitar).
2. Informar `App ID` e `App Secret` do app Meta.
3. Em `Authentication -> URL Configuration`, adicionar:
   - `Site URL`: `http://localhost:5173`
   - `Redirect URLs`: `http://localhost:5173/*`

Se não configurar, o endpoint `/auth/v1/authorize?provider=facebook` retornará `400 Bad Request`.

## Novos Endpoints
- `GET /api/clients`
- `POST /api/clients`
- `POST /api/clients/{id}/connect_meta`
- `POST /api/ig/refresh_all`
- `POST /api/cron/ig_refresh_all` (header `X-CRON-SECRET`)
- `GET /api/dashboard`
- `GET /api/comments?days=90`
- `GET /api/ig/stories`
- `GET /api/notes`
- `POST /api/notes`
- `PUT /api/notes/{note_id}`
- `POST /api/ai/summary`

## Fluxo de Produto (Meta-first)
1. App abre na tela de **Login**.
2. Usuário entra com **Meta** (Supabase Auth/Facebook).
3. Se for primeiro acesso, app abre **Onboarding**:
   - cria tenant (se necessário)
   - conecta OAuth Meta de ativos
   - faz discovery e seleção manual de Instagram/Ads
4. Após vincular, entra no **Dashboard**.
5. Em acessos recorrentes, se já houver conexão ativa, entra direto no dashboard.

## Handoff OAuth Persistente
- O handoff do OAuth da Meta agora é persistido na tabela `meta_oauth_handoffs`.
- Isso evita perder a sessão de discovery quando o backend reinicia ou quando há mais de uma instância rodando.
- Não há nova variável de ambiente para isso; basta aplicar a migração `20260416_000009_meta_oauth_handoffs.sql`.

## Operação Meta Ads
### Campos operacionais em `meta_connections`
O backend passa a manter estes campos durante refresh e sync:
- `token_expires_at`
- `token_last_refreshed_at`
- `last_validated_at`
- `last_sync_at`
- `last_sync_status`
- `last_error`
- `requires_reauth`
- `is_active`

Compatibilidade mantida:
- `expires_at` continua sendo atualizado junto com `token_expires_at`
- `last_synced_at` continua sendo atualizado junto com `last_sync_at`

### Rotinas
1. `token refresh`
   - valida e renova tokens ativos por conexão
   - se falhar a renovação, marca a conexão como `needs_reauth` e `requires_reauth=true`
2. `ads sync hourly`
   - roda por hora
   - usa janela recente segura, por padrão `7` dias
   - faz upsert idempotente nas tabelas pagas
3. `manual/backfill`
   - roda por cliente/período explícito
   - útil para recompor intervalo histórico ou forçar sync de uma conexão específica

### Job Runs / observabilidade
Cada execução relevante grava em `cron_job_runs`:
- `job_name`
- `client_id`
- `connection_id`
- `started_at`
- `finished_at`
- `status`
- `rows_upserted`
- `error`
- `payload_json`

## Endpoints Operacionais
- `POST /api/ads/sync`
- `POST /api/cron/token_refresh`
- `POST /api/cron/paid_sync`
- `POST /api/cron/paid_sync_hourly`
- `GET /api/meta/connections/{connection_id}/status`
- `POST /api/meta/connections/{connection_id}/refresh-token`
- `GET /api/jobs/runs`

## Testes rápidos via cURL
> Troque `$JWT` e `$CLIENT_ID`.

Listar clientes:
```bash
curl -H "Authorization: Bearer $JWT" \
  http://localhost:8000/api/clients
```

Criar cliente:
```bash
curl -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"name":"Nome da empresa"}' \
  http://localhost:8000/api/clients
```

Conectar Meta:
```bash
curl -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"access_token":"EA...","expires_at":"2026-07-01T00:00:00Z","ig_user_id":"1784..."}' \
  http://localhost:8000/api/clients/$CLIENT_ID/connect_meta
```

Refresh manual:
```bash
curl -X POST -H "Authorization: Bearer $JWT" -H "X-Client-Id: $CLIENT_ID" \
  "http://localhost:8000/api/ig/refresh_all?limit=40"
```

Sync manual / backfill de Ads:
```bash
curl -X POST \
  -H "Authorization: Bearer $JWT" \
  -H "X-Client-Id: $CLIENT_ID" \
  -H "Content-Type: application/json" \
  -d '{"connection_id":"YOUR_CONNECTION_ID","since":"2026-04-01","until":"2026-04-07"}' \
  http://localhost:8000/api/ads/sync
```

Refresh manual de token:
```bash
curl -X POST \
  -H "Authorization: Bearer $JWT" \
  -H "X-Client-Id: $CLIENT_ID" \
  http://localhost:8000/api/meta/connections/YOUR_CONNECTION_ID/refresh-token
```

Status da conexão:
```bash
curl -H "Authorization: Bearer $JWT" -H "X-Client-Id: $CLIENT_ID" \
  http://localhost:8000/api/meta/connections/YOUR_CONNECTION_ID/status
```

Consultar job runs:
```bash
curl -H "Authorization: Bearer $JWT" -H "X-Client-Id: $CLIENT_ID" \
  "http://localhost:8000/api/jobs/runs?limit=20"
```

Comentários:
```bash
curl -H "Authorization: Bearer $JWT" -H "X-Client-Id: $CLIENT_ID" \
  "http://localhost:8000/api/comments?days=90"
```

Notas:
```bash
curl -X POST -H "Authorization: Bearer $JWT" -H "X-Client-Id: $CLIENT_ID" -H "Content-Type: application/json" \
  -d '{"title":"Plano de Abril","body":"Testar 3 reels por semana"}' \
  http://localhost:8000/api/notes
```

IA:
```bash
curl -X POST -H "Authorization: Bearer $JWT" -H "X-Client-Id: $CLIENT_ID" \
  "http://localhost:8000/api/ai/summary?days=90"
```

## Comandos Locais Simples
Sem depender de curl, você pode rodar:

Refresh de tokens:
```bash
python server/run_jobs.py token-refresh
```

Sync horário de Ads:
```bash
python server/run_jobs.py ads-sync-hourly --days 7
```

Backfill manual:
```bash
python server/run_jobs.py ads-backfill --client-id "$CLIENT_ID" --connection-id "$CONNECTION_ID" --since 2026-04-01 --until 2026-04-07
```

Refresh manual de uma conexão:
```bash
python server/run_jobs.py refresh-token --connection-id "$CONNECTION_ID"
```

## Exemplos de Cron
Crontab local:
```bash
*/30 * * * * cd /Users/klebs/Desktop/mugo_metrics && /usr/bin/python3 server/run_jobs.py token-refresh >> /tmp/mugo_token_refresh.log 2>&1
0 * * * * cd /Users/klebs/Desktop/mugo_metrics && /usr/bin/python3 server/run_jobs.py ads-sync-hourly --days 7 >> /tmp/mugo_ads_sync.log 2>&1
```

Chamando API protegida por `CRON_SECRET`:
```bash
curl -X POST "http://localhost:8000/api/cron/token_refresh" \
  -H "X-CRON-SECRET: $CRON_SECRET"

curl -X POST "http://localhost:8000/api/cron/paid_sync_hourly?days=7" \
  -H "X-CRON-SECRET: $CRON_SECRET"
```

Render Cron / Vercel Cron:
- token refresh: a cada 30 minutos
- paid sync hourly: 1x por hora
- usar `X-CRON-SECRET` em todos os requests
- se quiser uma janela menor, ajustar `days=3`; se quiser mais resiliência, `days=7`

## Checklist de Validação
- Rodar a migração `20260417_000010_meta_ads_operational_stability.sql`
- Confirmar que `meta_connections` tem os novos campos operacionais
- Confirmar que `cron_job_runs` está sendo preenchida
- Executar `python server/run_jobs.py token-refresh`
- Executar `python server/run_jobs.py ads-sync-hourly --days 7`
- Validar `GET /api/meta/connections/{connection_id}/status`
- Validar `GET /api/jobs/runs`
- Validar `GET /api/dashboard/paid` com conexão saudável e com conexão em erro
- Confirmar que o dashboard continua exibindo o último dado persistido mesmo se a conexão estiver `needs_reauth`

## Segurança
- Não exponha `SUPABASE_SERVICE_ROLE_KEY` nem token Meta no frontend.
- Não logue `access_token`.
- Em produção, exija HTTPS e segredos fortes (`CRON_SECRET`, `TOKEN_ENCRYPTION_KEY`).
