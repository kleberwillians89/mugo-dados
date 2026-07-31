# Contratos do dashboard Mugô Dados

Todos os endpoints abaixo exigem bearer token e resolvem a empresa pelo
`client_id` explícito ou pelo header `X-Client-Id`. O backend valida membership;
`platform_admin` só acessa suporte quando escolhe uma empresa existente.

| Área | Endpoint principal | Permissão | Loading/erro | Cache |
| --- | --- | --- | --- | --- |
| Sessão global | `GET /api/platform/me` | usuário autenticado | shell imediato; erro de sessão isolado | sessão Supabase |
| Empresas comuns | `GET /api/clients` | membership | estado vazio sem vínculo | bootstrap da aplicação |
| Empresas globais | `GET /api/platform/companies` | `platform_admin` | lista com skeleton/erro | estado da página |
| Conexões oficiais | `GET /api/connections` | leitura tenant | cards independentes | estado do hub |
| Conexões Meta | `GET /api/clients/{client_id}/connections` | leitura tenant | Meta não derruba outras fontes | 5 minutos por tenant |
| Resumo orgânico | `GET /api/dashboard` | leitura tenant | skeleton dimensional; último valor preservado | tenant + conexão + período |
| Resumo pago | `GET /api/dashboard/paid` | leitura tenant | bloco isolado | tenant + conexão + período |
| Mídias | `GET /api/ig/media` | leitura tenant | paginação e cancelamento | tenant + conexão + período |
| Comentários | `GET /api/ig/comments` | leitura tenant | bloco isolado | tenant + conexão + período |
| Stories | `GET /api/ig/stories` | leitura tenant | indisponível ≠ zero | tenant + conexão + período |
| GA4 | `GET /api/google/ga4/report` | leitura tenant | sem eventos ≠ erro | tenant + período |
| Comércio legado | `GET /api/fbits/orders/summary` | leitura tenant | apresentado como e-commerce conectado | tenant + período |
| Shopify | `GET /api/shopify/report` | leitura tenant | bloco independente | tenant + período |

Erros `401` limpam sessão e estado tenant. `403` preserva a sessão e informa falta
de acesso, sem repetir a chamada. `429` e `5xx` são marcados como recuperáveis.

## Concessão inicial de administrador

A migration `20260801_000020_platform_admin_companies.sql` cria a estrutura e as
políticas, mas não fixa e-mail nem UUID no Git. Depois que o usuário administrativo
existir no Supabase Auth, um operador autorizado deve executar uma única vez,
substituindo o parâmetro pelo UUID real conferido no Auth:

```sql
insert into public.platform_admins (user_id, role, granted_by)
values ('<AUTH_USER_UUID>'::uuid, 'platform_admin', null)
on conflict (user_id) do update
set role = excluded.role;
```

Essa concessão não é uma membership de cliente. Toda abertura de empresa para
suporte continua exigindo seleção explícita e gera evento de auditoria.

## Configuração de runtime

- Frontend: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` e
  `VITE_API_BASE` (o fallback de produção aponta para o serviço Render oficial).
- Backend: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, origens CORS e os
  segredos OAuth documentados em `docs/oauth-setup.md`.

Nenhum valor secreto deve ser gravado no bundle ou no repositório.

## Registro de integrações

O catálogo público canônico do backend está em
`server/services/integration_catalog.py`. A apresentação tipada do frontend está
em `src/app/integrationRegistry.ts`. TikTok e Pinterest permanecem com
`platform_update_pending`; não possuem botão OAuth nem podem aparecer conectados.
