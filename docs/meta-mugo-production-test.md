# Mugô Dados — primeiro teste real com os ativos da Mugô

Roteiro operacional para executar linha por linha. Não registre aqui tokens, secrets, senhas nem IDs técnicos reais.

Base auditada: branch `fix/meta-app-review-production` (commit `5b4cac0`), em 2026-09-30.

## 0. Leia antes de começar

### Retorno do OAuth (corrigido nesta branch)

O callback Meta redireciona para
`https://dados.mugoagencia.com.br/?onboarding=1&client_id=…&meta_oauth=success&handoff=…&connection_id=…`.
Antes da correção, `resolveAuthenticatedView` (`src/App.tsx`) reescrevia a URL para `/meta` e descartava
a query. Agora o sinal de setup tem precedência (teste: `App — retorno do OAuth Meta` em
`src/App.onboardingNavigation.test.tsx`). O frontend corrigido precisa estar implantado antes do teste.

Se mesmo assim a seleção não abrir, o contorno é (em até 15 minutos, TTL do handoff):
Integrações → card Meta → campo **Autorização** → escolher a autorização recém-criada → **Selecionar ativos**.

### Contato das páginas legais

`/privacidade` e `/exclusao-de-dados` exibem `privacidade@mugoagencia.com.br`, definido em
`src/app/legalContact.ts` (fonte única). Confirme que a caixa recebe e-mails antes da submissão.

### Diferenciar erro de código de erro de configuração Meta

| Sinal | Provável origem |
|---|---|
| URL de retorno contém `meta_oauth=error&error=…` com texto da Meta (ex.: `access_denied`, `redirect_uri`) | Configuração Meta / usuário negou |
| `Configuração OAuth Meta incompleta. Missing environment variable(s): …` ao clicar Conectar | Variável ausente no Render |
| `OAUTH_STATE_SECRET deve ter ao menos 32 caracteres.` | Variável no Render |
| `Tabela de handoff OAuth não encontrada no Supabase…` | Migration não aplicada |
| Log Render `[meta_oauth][flow] … stage=callback_failed error_code=MetaApiError` | Graph API recusou (permissão/papel no app/ativo) |
| Log Render `stage=callback_failed error_code=RuntimeError/PermissionError` | State, tenant ou redirect URI (código/config) |
| `page_count=0` no log `stage=assets_discovered` | Usuário Meta sem acesso às Páginas ou não selecionou ativos no diálogo Login for Business |
| `instagram_count=0` com `page_count>0` | Instagram não é profissional ou não está vinculado à Página |
| `ad_account_count=0` | Usuário sem acesso à conta de anúncios ou não a selecionou no diálogo |

Logs: Render → serviço `mugo-dados-api` → Logs. Filtre por `[meta_oauth][flow]`, `[meta-organic-real]`,
`[ig_sync]`, `[ads_meta]`, `[tenant]`. Cada resposta da API traz `X-Request-ID`; o Onboarding mostra o
`request_id` no painel de diagnóstico.

## 1. Pré-requisitos (marcar todos antes de clicar em Conectar com Meta)

### Código
- [ ] Correções desta branch (retorno do OAuth, seletor, limpeza por empresa, período do Meta Ads) publicadas no frontend.
- [ ] `/privacidade` e `/exclusao-de-dados` em produção exibem `privacidade@mugoagencia.com.br`.
- [ ] Commit implantado no Render e na Vercel identificado (`GET https://api.dados.mugoagencia.com.br/api/version`).

### Banco / Supabase (somente leitura para verificar)
- [ ] Migrations até `20260820_000035_company_creation_idempotency.sql` aplicadas (a RPC `create_platform_company` com 8 argumentos precisa existir).
- [ ] Tabelas `oauth_sessions`, `meta_oauth_handoffs`, `integration_connections`, `meta_connections`, `dashboard_daily_metrics` existentes.
- [ ] O usuário do Kleber consta em `platform_admins` com `role = 'platform_admin'`.
- [ ] `20260929_000036_platform_company_permanent_deletion.sql`: não é necessária para este teste.

### Render (backend)
- [ ] `APP_ENV=production`
- [ ] `META_APP_ID`, `META_APP_SECRET`
- [ ] `META_OAUTH_REDIRECT_URI=https://api.dados.mugoagencia.com.br/api/oauth/meta/callback`
- [ ] `META_LOGIN_CONFIG_ID` (ID da Login Configuration, não o App ID)
- [ ] `OAUTH_STATE_SECRET` (≥ 32 caracteres) — ou `TOKEN_ENCRYPTION_KEY` ≥ 32 como fallback
- [ ] `TOKEN_ENCRYPTION_KEY` definido explicitamente (não rotacionar depois de conectar: tokens salvos deixam de ser decifráveis)
- [ ] `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- [ ] `SUPABASE_INVITE_REDIRECT_URL` (sem ela a criação de empresa falha e é revertida)
- [ ] `ALLOW_ORIGIN` com `https://dados.mugoagencia.com.br` como **primeiro** item (o callback Meta usa o primeiro item como destino)
- [ ] `CRON_SECRET` (sincronizações agendadas)
- [ ] `META_GRAPH_VERSION` vazio (padrão `v25.0`) ou no formato `vNN.N`

### Vercel (frontend)
- [ ] `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
- [ ] `VITE_API_BASE` apontando para o backend de produção (se vazio, o código usa `https://api.dados.mugoagencia.com.br`)

### Meta for Developers
- [ ] Facebook Login for Business habilitado; Login Configuration com as 7 permissões: `public_profile`, `pages_show_list`, `pages_read_engagement`, `instagram_basic`, `instagram_manage_insights`, `ads_read`, `business_management`.
- [ ] Valid OAuth Redirect URI exatamente igual ao callback acima (sem barra final).
- [ ] App Domains inclui `dados.mugoagencia.com.br`.
- [ ] O usuário do Facebook que fará o teste tem papel no app (Admin/Developer/Tester) enquanto não houver Advanced Access.

### Ativos da Mugô
- [ ] O usuário do Facebook tem acesso (pessoal ou via Business Manager) à Página da Mugô.
- [ ] O Instagram da Mugô é conta profissional (Business/Creator) vinculada a essa Página.
- [ ] O usuário tem acesso à conta de anúncios da Mugô.

## 2. Execução

| # | Ação | Resultado esperado | Endpoint | Se falhar |
|---|---|---|---|---|
| 1 | Acessar `https://dados.mugoagencia.com.br` | Tela de login | — | Vercel / `VITE_SUPABASE_*` |
| 2 | Login | Dashboard; menu com **Administração** | Supabase Auth; `platform_admins` e `clients` via Supabase | Sem “Administração” → usuário não é `platform_admin` |
| 3 | Administração → **+ Nova empresa** → Razão social `Mugô`, e-mail do responsável (o próprio e-mail) → Continuar ×3 → **Criar empresa** | “Empresa criada”. Aviso de que o responsável já tem conta é esperado | `POST /api/platform/companies` | 400 `Supabase Admin Invite não configurado` → `SUPABASE_INVITE_REDIRECT_URL`; `Não foi possível registrar a empresa agora` → RPC/migration 035 |
| 4 | Conferir a tabela da Administração | Mugô listada. Ela entra no seletor de empresas assim que for aberta (passo 5), sem F5 | `GET /api/platform/companies` | — |
| 5 | Clicar **Abrir empresa** | Abre o dashboard Meta vazio da Mugô; o seletor mostra “Mugô” | `POST /api/platform/companies/{id}/access` | 403/404 → permissão ou empresa |
| 6 | Menu **Integrações** (ou na tabela: ⋯ → **Fazer onboarding**) | Tela “Conexões de Mugô” | `GET /api/clients/{id}/integrations`, `GET /api/connections` | “Conexões de Cliente” → empresa ativa incorreta |
| 7–8 | Card Meta → **Conectar com Meta** | Redireciona para `facebook.com/v25.0/dialog/oauth` com `config_id` | `GET /api/oauth/meta/start?client_id=…` | Mensagem `Missing environment variable(s)` → Render |
| 9–10 | Autenticar com o usuário Meta da Mugô; selecionar Página, Instagram e conta de anúncios da Mugô no diálogo; autorizar | Diálogo lista as permissões da Login Configuration | Meta | Erro no diálogo → configuração Meta |
| 11 | Retorno automático | Volta para `dados.mugoagencia.com.br/?onboarding=1&meta_oauth=success…` e abre a seleção | `GET /api/oauth/meta/callback` → redirect | Cai em `/meta` → frontend corrigido não implantado (ver seção 0). `meta_oauth=error` → ler `error` |
| 12 | Conferir “Conta autorizada” | Nome/ID da conta Meta que autorizou | `GET /api/oauth/meta/discover-assets?client_id=…&handoff=…` | `Sessão OAuth não pertence ao cliente informado` → empresa ativa trocada durante o OAuth |
| 13–14 | Seção Páginas | Página da Mugô listada | idem | Lista vazia → ativos não selecionados no diálogo/sem acesso |
| 15–16 | Seção Instagram → marcar o Instagram da Mugô (e a Página correspondente) | Instagram com @ vindo da Meta | idem | Vazio com Página presente → Instagram não profissional/não vinculado |
| 17–18 | Seção Contas de anúncios → marcar a conta da Mugô | Conta `act_…` com nome | idem | Vazio → sem acesso/sem seleção |
| 19 | **Salvar** | “Meta conectada. Ativos persistidos e importação inicial concluída.” | `POST /api/clients/{id}/connections/link-assets` (inclui sync Ads 30 dias) e `POST /api/oauth/meta/{authorization_id}/organic/activate` (sync orgânico) | “Selecione explicitamente uma autorização…” → escolher o campo Autorização; “Os ativos foram salvos, mas a sincronização orgânica falhou. Código: …” → ver `[meta-organic-real]` e `[ig_sync]` |
| 20 | Aguardar sincronização | Status das conexões Instagram e Meta Ads ativos | `GET /api/clients/{id}/integrations` | `META_GRAPH_UNAVAILABLE` → Graph; `META_REAUTH_REQUIRED` → reconectar |
| 21 | Abrir **Meta** (dashboard) | Dados da Mugô | `GET /api/dashboard`, `/api/media`, `/api/comments`, `/api/dashboard/paid`, `/api/campaigns`; leituras Supabase `dashboard_*` | Vazio → verificar `stage=complete` nos logs |
| 22 | Perfil Instagram | username, seguidores | `/api/dashboard` | — |
| 23 | Orgânico | alcance, visitas ao perfil, interações | `/api/dashboard` | Métricas ausentes são reportadas como `unavailable_metrics` no sync |
| 24 | Mídia | Tabela de posts/Reels | `/api/media` | — |
| 25 | Insights de mídia | alcance/curtidas/comentários/salvos por post | `/api/media` | — |
| 26–28 | Meta Ads | investimento, impressões, alcance, cliques, ranking de campanhas, tabela de criativos | `/api/dashboard/paid`, `/api/campaigns` | Somente os últimos 30 dias são importados na conexão inicial |
| 29–30 | F5 | Mesma empresa e dados | bootstrap + `mugo_dados.active_client` no localStorage | — |
| 31–33 | Sair → entrar | Mugô continua configurada (a empresa ativa pode voltar para a primeira da lista: trocar para Mugô no seletor) | — | — |
| 34–35 | Trocar para outra empresa (inclusive com a tela de seleção de ativos aberta) | Nenhum dado nem ativo pendente da Mugô visível | todas as chamadas com `X-Client-Id` e `client_id` da nova empresa | Qualquer dado da Mugô → parar e registrar `request_id` |
| 36–37 | Voltar para Mugô | Dados da Mugô | — | — |

### Observações
- **Sincronizar agora** do card Meta Ads envia apenas `connection_id`; o backend usa o período padrão de 30 dias.

### Não usar durante o teste
- Campos manuais de Page ID / Instagram ID / Ad Account ID (fallback técnico; não fazem parte do fluxo principal).

## 3. Registro do teste

| Item | Valor |
|---|---|
| Data/hora | |
| Commit backend (`/api/version`) | |
| Commit frontend | |
| `request_id` do callback | |
| `page_count` / `instagram_count` / `ad_account_count` | |
| Resultado final | |
