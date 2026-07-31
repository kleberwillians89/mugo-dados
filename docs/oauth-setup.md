# Mugô Dados — configuração externa

Domínios oficiais:

- Frontend: `https://dados.mugoagencia.com.br`
- Backend: `https://api.dados.mugoagencia.com.br`

## Escopo atual

- Um único App empresarial Meta “Mugô Dados”, com seleção de Página, Instagram profissional e conta de anúncios.
- Um único projeto Google Cloud “Mugô Dados”, com uma autorização por empresa e seleções separadas de GA4 e Google Ads.
- Um único app Shopify “Mugô Dados”, distribuído para lojas clientes e isolado por empresa e domínio `myshopify.com`.
- TikTok e Pinterest não possuem OAuth ou endpoints nesta etapa; aparecem somente como “Aguardando atualização da plataforma”.
- FBits é legado preservado e não recebe expansão nesta etapa.

## Callbacks

Produção:

- Supabase convite: `https://dados.mugoagencia.com.br/?type=invite`
- Supabase recuperação: `https://dados.mugoagencia.com.br/?type=recovery`
- Meta: `https://api.dados.mugoagencia.com.br/api/oauth/meta/callback`
- Google: `https://api.dados.mugoagencia.com.br/api/oauth/google/callback`
- Shopify: `https://api.dados.mugoagencia.com.br/api/oauth/shopify/callback`
- Shopify webhooks: `https://api.dados.mugoagencia.com.br/api/webhooks/shopify`

Desenvolvimento:

- Frontend: `http://localhost:5173`
- Supabase convite: `http://localhost:5173/?type=invite`
- Supabase recuperação: `http://localhost:5173/?type=recovery`
- Meta: `http://localhost:8000/api/oauth/meta/callback`
- Google: `http://localhost:8000/api/oauth/google/callback`
- Shopify: `http://localhost:8000/api/oauth/shopify/callback`

Shopify webhooks exigem um túnel HTTPS durante desenvolvimento.

## Frontend / Vercel

- `VITE_API_BASE`
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_ALLOW_LOCAL_AUTH`
- `VITE_AUTH_DEBUG`
- `VITE_DASH_DEBUG`

Nunca configure `service_role`, App Secret ou token de plataforma no Vercel.

## Backend / Render

- `APP_ENV`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_INVITE_REDIRECT_URL`
- `TOKEN_ENCRYPTION_KEY`
- `OAUTH_STATE_SECRET`
- `ALLOW_ORIGIN`
- `FRONTEND_URL`
- `CRON_SECRET`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

Em produção: `ALLOW_NO_AUTH=false` e `ALLOW_UNVERIFIED_JWT_DEV=false`.

## Supabase Auth

1. Em URL Configuration, use o frontend oficial como Site URL.
2. Adicione os quatro redirects de convite/recuperação, oficiais e locais.
3. Habilite e-mail/senha e desabilite cadastro público.
4. Configure SMTP próprio e os templates de convite e recuperação.
5. Revise as migrations `000018` e `000019` antes de aplicá-las remotamente.
6. Confirme que a chave `service_role` existe somente no Render.

## Meta for Developers

Variáveis:

- `META_APP_ID`
- `META_APP_SECRET`
- `META_OAUTH_REDIRECT_URI`
- `META_OAUTH_STATE_SECRET`
- `META_OAUTH_SCOPES`

Checklist:

1. Abra o app empresarial da Mugô.
2. Em Facebook Login, cadastre os callbacks Meta oficial e local.
3. Configure domínio, política de privacidade e exclusão de dados.
4. Solicite revisão somente dos escopos realmente usados por Instagram e Ads.
5. Confirme que o discovery lista e permite selecionar separadamente Página, Instagram profissional e conta de anúncios.

## Google Cloud e Google Ads

Variáveis:

- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`
- `GOOGLE_ADS_DEVELOPER_TOKEN`

Checklist:

1. Crie um projeto dedicado ao Mugô Dados.
2. Ative Google Analytics Admin API, Google Analytics Data API e Google Ads API.
3. Configure a OAuth Consent Screen e os domínios oficiais.
4. Crie uma credencial OAuth Web e cadastre os callbacks oficial e local.
5. Adicione usuários de teste enquanto o app estiver em modo de teste.
6. No Google Ads API Center da conta administradora, solicite o developer token.
7. Sem developer token, GA4 funciona e Google Ads informa configuração pendente.
8. Para MCC, mantenha a conta administradora como `login_customer_id`; a seleção de contas filhas será ampliada sobre essa estrutura.

## Shopify Partner Dashboard

Variáveis:

- `SHOPIFY_CLIENT_ID`
- `SHOPIFY_CLIENT_SECRET`
- `SHOPIFY_OAUTH_REDIRECT_URI`
- `SHOPIFY_WEBHOOK_URL`
- `SHOPIFY_APP_SECRET`

Checklist:

1. Crie o app e defina a App URL para o frontend oficial.
2. Cadastre os callbacks Shopify oficial e local.
3. Configure apenas `read_orders`, `read_customers` e `read_products`.
4. Cadastre webhooks de pedidos, clientes e `app/uninstalled`.
5. Cadastre `customers/data_request`, `customers/redact` e `shop/redact`.
6. Aponte todos ao endpoint oficial de webhooks.

## Vercel

1. Configure somente as variáveis `VITE_*`.
2. Vincule `dados.mugoagencia.com.br` ao projeto correto.
3. Configure fallback SPA para rotas privadas.

## Render

1. Configure todas as variáveis privadas do backend.
2. Vincule `api.dados.mugoagencia.com.br` ao serviço correto.
3. Configure health check em `/health`.
4. Configure cron/worker somente quando a infraestrutura oficial estiver definida.

## Rotação e operação

- Rotacionar `TOKEN_ENCRYPTION_KEY` exige recriptografar os tokens antes de remover a chave antiga.
- Trocar `OAUTH_STATE_SECRET` invalida autorizações em andamento.
- Desconectar preserva o histórico.
- Checkpoints são separados por empresa, conexão e recurso.
