# PR B — OAuth MCP, consentimento e auditoria

Candidato local: `feat/mcp-oauth`, `/tmp/mugo-mcp-oauth-checkout`.
A árvore contém PR A + PR B. As duas branches ainda apontam à mesma base, pois commits exigem
nova autorização pelas regras locais. O patch incremental B é preparado contra o conteúdo final A;
a dependência real entre branches precisa ser estabelecida ao criar os commits, antes de abrir PRs.
Nenhum commit, push, PR, merge, deploy ou alteração de configuração remota foi executado.

## Mudanças e segurança

- Discovery RFC 9728/8414, DCR, authorize/token/revoke e 401 MCP com `WWW-Authenticate`.
- `MCP_PUBLIC_URL` é o recurso exato HTTPS terminado em `/mcp`; `MCP_FRONTEND_URL` é origem HTTPS
  explícita. Não deriva issuer/callback de cabeçalhos não confiáveis.
- Redirect exato contra cadastro e `MCP_ALLOWED_REDIRECT_URIS`, state obrigatório, PKCE S256.
- Cliente público (`token_endpoint_auth_method=none`), código de cinco minutos consumido atomicamente.
- Tokens opacos: access até uma hora; família refresh até 30 dias, rotação obrigatória e reuso revoga família.
  Código e tokens só são persistidos como SHA-256. A raiz da família serializa rotações/revogações com `FOR UPDATE`.
- JWT Supabase verificado pelo fluxo existente, sem fallback de JWT não verificado nem bypass local para consentimento.
- `company_id` continua revalidado por chamada com permissões frescas; o token não guarda memberships em cache.
- Tela independente de conexão reutiliza o Login existente, preservando URL OAuth durante autenticação.
  Menu da conta oferece conexão; consentimento mostra empresas autorizadas, autorizar/cancelar;
  gestão mostra URL/cópia, instruções, conexões e revogação própria. Sem mudança nas rotas OAuth dos providers.
- Auditoria isolada das ferramentas: apenas usuário, empresa autorizada (ou nulo se negada), nome de tool,
  datas, status e duração. Sem texto de argumentos/resposta. Falha ao auditar não libera conteúdo sem registro.
- Somente autenticação/auditoria MCP escrevem nas quatro tabelas novas. Tools não escrevem dados de negócio.
- Requisição OAuth até 16 KiB, orçamento 9 s, registro/discovery/token/revoke com teto global 120/min;
  MCP limita verificação de tokens concorrente, leituras, taxa por hash do token e tamanho da resposta.
- SDK e erros Supabase têm redação contextual. Não se registram tokens, prompts, respostas ou corpos de erro.

## Validação local

- Testes direcionados: `test_mcp_readonly`, `test_mcp_oauth`, `test_migration_bootstrap_contract`: 41 aprovados, incluindo SQL real e sem skips quando o socket está configurado.
- O teste PostgreSQL opcional é executado separadamente e também na suíte completa com socket configurado;
  sem essa configuração aparece como skip explícito, nunca como homologação de SQL.
- PostgreSQL descartável, sem TCP: PKCE inválido, código expirado/reutilizado, recurso incorreto,
  rotação/reuso de refresh, revogação familiar e negação de acesso browser. Transação de fixtures revertida.
- Migration executada duas vezes SOMENTE no cluster descartável para verificar idempotência.
- Frontend: 754 testes passaram; typecheck, eslint e build com exit 0.
- Suíte backend completa: 1.716 executados, 1.713 aprovados; as mesmas três falhas da main documentadas no PR A. Não foram ocultadas.
- Não há navegador conectado; consentimento visual mobile/desktop e handshake real no Claude NÃO foram homologados.
- Nenhuma credencial de produção foi utilizada. Não houve geração de IA, refresh, backfill ou escrita remota.

```sh
PYTHONPATH=server:server/tests /tmp/mugo-mcp-venv/bin/python -m unittest test_mcp_readonly test_mcp_oauth test_migration_bootstrap_contract
PYTHONPATH=server:server/tests /tmp/mugo-mcp-venv/bin/python -m unittest discover -s server/tests
npm run typecheck
npx eslint src
npx vitest run
npm run build
PYTHONPATH=server /tmp/mugo-mcp-venv/bin/python -m compileall -q server
git diff --check
```

O contrato SQL pode ser reexecutado somente com o cluster descartável do roteiro:
`MCP_TEST_PG_SOCKET=/tmp/mugo-mcp-pg/socket`, usuário `mcp_test_owner`, porta de socket 55469.
O servidor local é parado ao terminar; nenhum banco existente é usado.

## Aplicação manual da migration 045 — Kleber

1. Revisar integralmente `supabase/migrations/20261027_000045_mcp_oauth.sql` (SQL abaixo).
2. Confirmar que existem apenas as 44 migrations anteriores e que o ambiente é o desejado.
3. Fazer revisão/backup habitual. No SQL Editor autorizado, executar o arquivo integral em transação.
   Não executar por este agente nem sincronizar migrations indiscriminadamente.
4. Verificar quatro tabelas, RLS ligado, ausência de grants browser e funções executáveis somente por service_role.
5. Manter flag desligada até código, schema, allowlist e URLs estarem conferidos.

O SQL cria somente estruturas novas; não altera RLS, tabelas ou regras de receita existentes.
Não há segredo novo a copiar para a interface.

## Como conectar no claude.ai após autorização de publicação e homologação

Configuração manual não sensível no backend (não executada):

```text
MCP_ENABLED=true
MCP_PUBLIC_URL=https://api.dados.mugoagencia.com.br/mcp
MCP_FRONTEND_URL=https://dados.mugoagencia.com.br
MCP_ALLOWED_REDIRECT_URIS=https://claude.ai/api/mcp/auth_callback
MCP_PILOT_CLIENT_IDS=<IDs autorizados no piloto, ou vazio>
```

1. Publicar A, depois B, sem habilitar bypass local em produção; aplicar 045 manualmente antes de habilitar.
2. Conferir discovery e 401 sem token em `/mcp`.
3. Menu Mugô → Conectar ao Claude → copiar URL.
4. Claude → Configurações → Conectores → adicionar conector personalizado.
5. Entrar no Mugô, revisar empresas e autorizar. A disponibilidade do recurso depende da conta/plano Claude.
6. Pedir listagem de empresas, freshness e indicadores de uma empresa autorizada, sem sincronizar nem gerar IA no Mugô.
7. Repetir com outro usuário/tenant, remover membership de uma conta de teste autorizada e conferir negação seguinte.
8. Revogar a conexão e comprovar 401. Testar mobile e conta viewer; nunca acessar tenant de terceiros.

Callback confirmado na documentação oficial atual: https://claude.com/docs/connectors/building/authentication .
Não foram acrescentados callbacks presumidos para outros domínios. Protocolos do SDK pinado:
2024-11-05, 2025-03-26, 2025-06-18 e 2025-11-25; negociação real com Claude permanece pendente.
Referências de autorização/transporte constam no PR A; grants e RLS seguem também
https://supabase.com/docs/guides/api/securing-your-api .

## Limitações e rollback

Valem todas as omissões e limites de dados do PR A, inclusive textos livres, agregados de compradores
indisponíveis e teto canônico de 366 dias. Não há correção de regra de KPI por este módulo.
Referências opacas não devem ser usadas para comparar identidades entre chamadas.
Histórico textual salvo não é liberado como supostamente anônimo. A UI mostra erros compreensíveis,
mas testes de DOM não substituem navegador/autenticação reais.

Retenção deve ser operada posteriormente em rotina autorizada: códigos expirados, famílias totalmente
expiradas e auditoria conforme política de retenção. NÃO excluir a raiz de família ainda válida, mesmo
que seu access esteja revogado/rotacionado. Esta entrega não agenda nem executa limpezas.

Rollback seguro: desligar flag para fechar todos os endpoints novos; reverter B antes de A se necessário,
preservando tabelas/dados existentes. Não executar DROP, restaurar banco ou revogar conexões de providers.
A desativação da flag não apaga tokens; para um incidente de segurança, revogar famílias por procedimento
administrativo autorizado antes de eventual reativação.

GO para revisão dos candidatos locais; NO-GO para produção antes de migration manual,
revisão das limitações, QA visual e conexão real com duas identidades autorizadas.

## SQL integral proposto (não aplicado remotamente)

```sql
-- Aplicação manual; não altera tabelas, RLS ou permissões existentes.
begin;
create table if not exists public.mcp_oauth_clients (
  id uuid primary key default gen_random_uuid(),
  client_name text not null check (length(client_name) between 1 and 100),
  redirect_uris jsonb not null,
  created_at timestamptz not null default now()
);
create table if not exists public.mcp_oauth_codes (
  code_hash text primary key check (length(code_hash)=64),
  user_id uuid not null references auth.users(id) on delete cascade,
  oauth_client_id uuid not null references public.mcp_oauth_clients(id) on delete cascade,
  redirect_uri text not null, resource text not null, challenge text not null,
  expires_at timestamptz not null default now() + interval '5 minutes',
  created_at timestamptz not null default now()
);
create table if not exists public.mcp_oauth_tokens (
  id uuid primary key,
  family_id uuid not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  oauth_client_id uuid not null references public.mcp_oauth_clients(id) on delete cascade,
  resource text not null,
  access_hash text unique not null check (length(access_hash)=64),
  refresh_hash text unique not null check (length(refresh_hash)=64),
  access_expires_at timestamptz not null,
  refresh_expires_at timestamptz not null,
  rotated_at timestamptz, revoked_at timestamptz,
  last_used_at timestamptz, created_at timestamptz not null default now()
);
create index if not exists mcp_tokens_family_idx on public.mcp_oauth_tokens(family_id);
create index if not exists mcp_tokens_owner_idx on public.mcp_oauth_tokens(user_id,created_at desc);
create table if not exists public.mcp_audit_events (
  id bigint generated by default as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  client_id text, tool text not null,
  period_start date, period_end date,
  status text not null check (status in ('ok','denied','unavailable')),
  duration_ms integer not null check (duration_ms>=0),
  created_at timestamptz not null default now()
);
create index if not exists mcp_audit_created_idx on public.mcp_audit_events(created_at);

-- Troca de código e criação dos tokens na MESMA transação; código nunca reutilizável.
create or replace function public.mcp_exchange_code(
  p_code_hash text, p_client_id uuid, p_redirect_uri text, p_resource text,
  p_challenge text, p_access_hash text, p_refresh_hash text
) returns boolean language plpgsql security invoker set search_path=public,pg_temp as $$
declare c public.mcp_oauth_codes; f uuid := gen_random_uuid();
begin
  select * into c from public.mcp_oauth_codes where code_hash=p_code_hash for update;
  if not found or c.expires_at<=now() or c.oauth_client_id<>p_client_id
     or c.redirect_uri<>p_redirect_uri or c.resource<>p_resource or c.challenge<>p_challenge then
    return false;
  end if;
  delete from public.mcp_oauth_codes where code_hash=p_code_hash;
  insert into public.mcp_oauth_tokens(id,family_id,user_id,oauth_client_id,resource,access_hash,refresh_hash,access_expires_at,refresh_expires_at)
    values(f,f,c.user_id,p_client_id,p_resource,p_access_hash,p_refresh_hash,now()+interval '1 hour',now()+interval '30 days');
  return true;
end $$;

-- Todas as rotações/revogações de uma família serializam pelo registro raiz.
-- O registro raiz deve permanecer até o término da família, inclusive após rotação.
create or replace function public.mcp_rotate_refresh(
  p_refresh_hash text, p_client_id uuid, p_resource text, p_access_hash text, p_new_refresh_hash text
) returns boolean language plpgsql security invoker set search_path=public,pg_temp as $$
declare t public.mcp_oauth_tokens; root public.mcp_oauth_tokens;
begin
  select * into t from public.mcp_oauth_tokens where refresh_hash=p_refresh_hash;
  if not found then return false; end if;
  select * into root from public.mcp_oauth_tokens where id=t.family_id for update;
  if not found or root.refresh_expires_at<=now() or t.oauth_client_id<>p_client_id or t.resource<>p_resource then return false; end if;
  select * into t from public.mcp_oauth_tokens where refresh_hash=p_refresh_hash;
  if t.rotated_at is not null then
    update public.mcp_oauth_tokens set revoked_at=coalesce(revoked_at,now()) where family_id=t.family_id;
    return false;
  end if;
  if t.revoked_at is not null or t.refresh_expires_at<=now() then return false; end if;
  update public.mcp_oauth_tokens set rotated_at=now(),revoked_at=now() where id=t.id;
  insert into public.mcp_oauth_tokens(id,family_id,user_id,oauth_client_id,resource,access_hash,refresh_hash,access_expires_at,refresh_expires_at)
    values(gen_random_uuid(),t.family_id,t.user_id,p_client_id,p_resource,p_access_hash,p_new_refresh_hash,
           least(now()+interval '1 hour',root.refresh_expires_at),root.refresh_expires_at);
  return true;
end $$;

create or replace function public.mcp_revoke_family(p_token_hash text, p_client_id uuid)
returns boolean language plpgsql security invoker set search_path=public,pg_temp as $$
declare f uuid;
begin
  select family_id into f from public.mcp_oauth_tokens
    where oauth_client_id=p_client_id and (access_hash=p_token_hash or refresh_hash=p_token_hash) limit 1;
  if not found then return false; end if;
  perform id from public.mcp_oauth_tokens where id=f for update;
  update public.mcp_oauth_tokens set revoked_at=coalesce(revoked_at,now()) where family_id=f;
  return true;
end $$;

alter table public.mcp_oauth_clients enable row level security;
alter table public.mcp_oauth_codes enable row level security;
alter table public.mcp_oauth_tokens enable row level security;
alter table public.mcp_audit_events enable row level security;
revoke all on table public.mcp_oauth_clients,public.mcp_oauth_codes,public.mcp_oauth_tokens,public.mcp_audit_events from public,anon,authenticated;
grant all on table public.mcp_oauth_clients,public.mcp_oauth_codes,public.mcp_oauth_tokens,public.mcp_audit_events to service_role;
revoke all on sequence public.mcp_audit_events_id_seq from public,anon,authenticated;
grant usage,select on sequence public.mcp_audit_events_id_seq to service_role;
revoke all on function public.mcp_exchange_code(text,uuid,text,text,text,text,text),public.mcp_rotate_refresh(text,uuid,text,text,text),public.mcp_revoke_family(text,uuid) from public,anon,authenticated;
grant execute on function public.mcp_exchange_code(text,uuid,text,text,text,text,text),public.mcp_rotate_refresh(text,uuid,text,text,text),public.mcp_revoke_family(text,uuid) to service_role;
commit;

```
