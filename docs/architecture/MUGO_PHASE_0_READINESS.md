# Fase 0 — Prontidão para o MCP

**Código auditado:** `badcb97` (`origin/main`)
**Data:** 2026-10-23
**Natureza:** somente leitura. Nenhum SQL de escrita, nenhuma migration aplicada, nenhum deploy, nenhum dado alterado, nenhum push. Os 65 arquivos modificados da sua árvore não foram tocados; nenhum worktree foi apagado.

Convenção: **[F]** fato verificado, **[S]** suposição explícita, **[?]** não verificável neste ambiente.

---

## 0. Projeto Supabase de produção — IDENTIFICADO

**Atualização de 2026-10-23.** O projeto foi identificado. O acesso continua pendente.

| Item | Valor |
|---|---|
| **Project ref** | **`rxjonbqkluzavozzmhze`** |
| **Hostname público** | `rxjonbqkluzavozzmhze.supabase.co` |
| **Supabase Studio** | `https://supabase.com/dashboard/project/rxjonbqkluzavozzmhze` |

**[F] Não é o `crm_mugo`** (`hdyjuyhiybjqvxsukmbn`), e não é nenhum dos três projetos visíveis na conta em que o CLI está autenticado. O projeto do Mugô Dados está em **outra conta ou organização Supabase**.

### Como foi identificado, e por que a fonte é legítima

**[F]** O repositório **não contém** nenhuma referência ao projeto. Verificado:

| Fonte | Resultado |
|---|---|
| `render.yaml` | **[F]** não menciona Supabase. Declara só 3 nomes: `APP_ENV`, `PYTHON_VERSION`, `SHOPIFY_OAUTH_REDIRECT_URI` |
| `vercel.json` | **[F]** nenhuma variável de ambiente |
| `.env.example`, `server/.env.example` | **[F]** apenas nomes, valores vazios |
| Histórico completo do git | **[F]** nenhum hostname `*.supabase.co` jamais commitado; nenhum `.env` real jamais commitado |

**Isto é postura de segurança correta e vale registrar como achado positivo:** os segredos vivem só no dashboard do Render e nunca entraram no versionamento.

**[F]** O ref veio do **bundle público do frontend** em `https://dados.mugoagencia.com.br`. `VITE_SUPABASE_URL` é público por desenho — vai para o JavaScript entregue a qualquer visitante, junto da anon key, e é com ele que o browser faz login. Extraí **somente o hostname**, com `grep` restrito ao padrão `[a-z0-9]{20}\.supabase\.co`. Nenhum outro conteúdo do bundle foi impresso, lido ou guardado.

**[S]** O backend usa o mesmo projeto: ele valida o JWT do browser chamando `{SUPABASE_URL}/auth/v1/user` (`server/services/auth.py:111`), o que só funciona se os dois apontarem para a mesma instância de Auth. Confirme no passo 1 do procedimento da seção 4.0.

### Confirmação cruzada, se quiser validar

**No Render** — `https://dashboard.render.com` → serviço **`mugo-dados`** → **Environment**:

- `SUPABASE_URL` deve ser `https://rxjonbqkluzavozzmhze.supabase.co`.
- **Não revele** `SUPABASE_SERVICE_ROLE_KEY` nem `SUPABASE_ANON_KEY`. Nada além do hostname é necessário.
- Confira também os 13 serviços cron: **[F]** eles não declaram `APP_ENV` no `render.yaml`, e isso é item da seção 7.4.

**No Supabase** — `https://supabase.com/dashboard`:

- Se `rxjonbqkluzavozzmhze` não aparecer na lista, você está logado na conta errada. Troque de conta ou de organização.
- O ref aparece na URL do projeto e em **Project Settings → General → Reference ID**.
- **[F]** A conta à qual o CLI local está autenticado **não** contém este projeto. Para usar o CLI contra ele seria preciso `supabase login` na conta correta e `supabase link --project-ref rxjonbqkluzavozzmhze` — **e nada disso é necessário para esta fase**, que precisa apenas do SQL Editor.

---

## 1. Estado do banco

### 1.1 O banco não foi lido. Nada foi simulado.

**Esta é a conclusão principal da Tarefa 1, e ela é negativa.** As perguntas 1, 3, 4, 5 e 6 do seu pedido **não podem ser respondidas** daqui. Elas dependem de medição no banco, e a medição não foi possível.

O projeto está identificado (seção 0), mas **não há credencial para consultá-lo daqui**. As perguntas 1, 3, 4, 5 e 6 do pedido continuam dependendo da medição da seção 4, que agora pode ser executada por você no projeto certo.

O que foi testado, e o resultado de cada tentativa:

| Caminho | Resultado |
|---|---|
| `.env` no projeto | **[F]** não existe. Só `.env.example`, que traz apenas as chaves `VITE_*` do frontend |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` no shell | **[F]** ausentes |
| CLI `supabase` autenticado | **[F]** sim, e com projeto vinculado |
| Projeto vinculado | **[F]** `crm_mugo` (`hdyjuyhiybjqvxsukmbn`) — **outro sistema**, não o Mugô Dados |
| Execução de SQL arbitrário pelo CLI | **[F]** indisponível. `supabase db` oferece só `diff`, `dump` e `push` |
| `psql` direto no pooler | **[F]** sem senha armazenada; a tentativa foi bloqueada pelo classificador de segurança, e não insisti |

### 1.2 Um alerta sobre interpretação, porque o erro aqui seria grave

`supabase migration list` **funciona** e produz uma saída que parece responder à sua pergunta 1: todas as 44 migrations locais aparecem com `remote: ""`, ou seja, não aplicadas.

**Essa leitura estaria errada, e eu não a adoto.** O projeto vinculado é o `crm_mugo`, cujo histórico remoto usa outra convenção de nomes inteiramente (`202607130001`, `202607140001`, …). A saída compara as migrations do Mugô Dados contra o banco do CRM — são sistemas diferentes. O resultado diz apenas que as migrations de um projeto não estão no banco de outro, o que é esperado e não informa nada sobre produção.

Nenhum dos três projetos da conta se chama `mugo-dados`: `santocircuito@gmail.com's Project` (INACTIVE), `crm_mugo` (ACTIVE, vinculado) e `cafifa-operacoes` (INACTIVE). **[S]** O banco do Mugô Dados é apontado por `SUPABASE_URL` nas variáveis do Render, que não são visíveis daqui.

### 1.3 O que **foi** confirmado, por leitura do código

Tudo nas seções 2 e 3 abaixo vem do SQL e do Python do repositório — o **estado esperado**. É contra ele que a medição da seção 4 deve ser comparada.

**[F] As três migrations declaram, no próprio corpo, que não foram aplicadas:**

| Migration | Declaração literal |
|---|---|
| `20261002_000038_browser_credential_lockdown.sql` | `-- MIGRATION LOCAL — revisar e aplicar remotamente só depois de validada.` |
| `20261006_000042_ecommerce_browser_lockdown.sql` | `-- NÃO APLICADA. Criada nesta rodada e deixada pendente de propósito.` |
| `20261022_000044_order_attribution.sql` | `-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.` |

Isto é declaração de intenção do autor, **não** medição do banco. As três podem ter sido aplicadas manualmente depois sem que o comentário fosse atualizado. **A seção 4 existe para resolver essa dúvida.**

---

## 2. O que cada migration deveria produzir

Resposta à sua pergunta 2. **[F]** Derivado linha a linha do SQL.

### 2.1 Migration 038 — `browser_credential_lockdown`

| Alvo | Operação esperada |
|---|---|
| `clients` | `revoke all from anon, authenticated` **e** `grant select (id, name, trade_name) to authenticated` — allowlist de colunas, para que `ig_access_token` deixe de ser legível |
| `meta_connections` | `enable row level security` + `revoke all from anon, authenticated` + `grant all to service_role` |
| `meta_oauth_handoffs` | idem |
| `shopify_refunds` | idem |
| `acquire_client_job_lock(text,text,integer)` | `revoke all from public, anon, authenticated` + `grant execute to service_role` |
| `release_client_job_lock(text,text)` | idem |

**[F]** Usa `to_regclass` para tolerar tabela ausente, é idempotente, e termina com `notify pgrst, 'reload schema'`.

**[F]** O motivo declarado para o lockdown dos RPCs: *"Sem isto, qualquer pessoa com a anon key travava/soltava locks de sync."*

### 2.2 Migration 042 — `ecommerce_browser_lockdown`

**[F]** Para as 6 tabelas `fbits_orders`, `fbits_order_items`, `shopify_customers`, `shopify_orders`, `shopify_order_items`, `shopify_webhook_events`:

```
enable row level security
revoke all from anon, authenticated
grant all to service_role
```

**[F]** A policy `tenant_member_select` da migration 018 **permanece** e é mantida de propósito — torna-se inócua para `anon`/`authenticated` porque, sem privilégio de tabela, a policy nem é avaliada.

**[F]** O diagnóstico que a própria migration registra, e que é a chave de toda esta fase:

> *"A migration 018 ligou RLS nelas e criou a policy `tenant_member_select`, mas NÃO revogou os grants. O privilégio de tabela é verificado ANTES da RLS."*

E a consequência, dividida com honestidade pelo autor: **não há vazamento entre empresas hoje** (a policy filtra), e sim **duas falhas de postura** — um `viewer` lê pelo browser o `raw_payload` que o backend nunca lhe entrega, e a policy passa a ser a única barreira, de modo que qualquer policy nova permissiva converte o grant em exposição ampla.

**[F]** Confirmei a premissa na migration 018: ela aplica `enable row level security` + `tenant_member_select` às 6 tabelas em laço, **sem revoke**. O `revoke` aparece em 018 apenas para `integration_connections` — que é precisamente por isso a única do grupo já fechada.

### 2.3 Migration 044 — `order_attribution`

**[F]** Puramente aditiva. **Nenhuma alteração de permissão** — o comentário diz: *"nenhuma permissão muda (as duas tabelas seguem com o RLS e os grants que já tinham)"*.

- 9 colunas `text` em `shopify_orders` e as mesmas 9 em `fbits_orders`: `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `origin_channel`, `origin_detail`, `referrer_domain`, `attribution_source`.
- 2 índices: `idx_shopify_orders_client_origin`, `idx_fbits_orders_client_origin`.
- Tudo com `if not exists`.

### 2.4 Dependências entre as migrations

Resposta direta: **as três são independentes e podem ser aplicadas em qualquer ordem.**

| Par | Relação |
|---|---|
| 038 ↔ 042 | conjuntos de tabelas disjuntos. Independentes |
| 044 ↔ 042 | tocam as mesmas tabelas (`shopify_orders`, `fbits_orders`) mas **eixos diferentes**: 044 adiciona colunas, 042 altera grants. Colunas novas herdam o grant de tabela, então qualquer ordem produz o mesmo estado final |
| 018 → 042 | 018 é **pré-requisito lógico** (criou RLS e a policy). **[S]** Está aplicada, pois é de 2026-07-30 e o sistema funciona; a medição da seção 4 confirma |
| 021 → controle | `ai_analyses` recebeu RLS **e** revoke em 021. Serve de **caso de controle** da medição |

**[F]** As três são idempotentes. Reaplicar é seguro.

---

## 3. Riscos reais, tabela por tabela

Resposta às suas perguntas 3, 4 e 5. Severidade sob a hipótese **[S]** de que 038 e 042 estejam pendentes e os grants default do Supabase estejam em vigor — hipótese que a seção 4 testa.

### 3.1 As 4 tabelas descobertas na auditoria

**[F] Verificado agora: nenhuma das quatro tem qualquer `enable row level security`, `create policy`, `revoke` ou `grant` em nenhuma das 44 migrations.** Elas dependem exclusivamente do grant default. E **nenhuma** das migrations 038/042 as cobre.

| Tabela | Colunas sensíveis | Risco | Severidade |
|---|---|---|---|
| **`fbits_order_daily_stats`** | `client_id`, `receita_oficial`, `pedidos`, `ticket_medio`, `clientes`, `produtos_vendidos` | **Receita diária por empresa.** Sem RLS e sem policy, qualquer usuário autenticado leria o faturamento de **todas** as empresas. Dois clientes concorrentes na mesma plataforma leriam o resultado um do outro | **Alta** |
| **`cron_locks`** | `client_id`, `job_name`, `locked_until` | **Caminho de escrita, não de leitura.** Ver 3.2 | **Alta (disponibilidade)** |
| **`cron_job_runs`** | `client_id`, `ad_account_id`, `error`, `payload_json` | Expõe a carteira de clientes, IDs de conta de anúncio e `payload_json` — jsonb livre escrito pelos jobs de sync. `error` pode conter mensagem de API | **Média** |
| **`meta_token_events`** | `client_id`, `event_type`, `ok`, `details_json` | Ver 3.3 | **Média-baixa** |

### 3.2 `cron_locks` — a 038 fechou o RPC e deixou a tabela aberta

Este é o achado novo desta fase, e ele decorre da lógica do próprio projeto.

**[F]** A migration 038 revoga `execute` em `acquire_client_job_lock` e `release_client_job_lock`, com o motivo escrito: *"qualquer pessoa com a anon key travava/soltava locks de sync."*

**[F]** Mas `acquire_client_job_lock` é `security definer` e o seu corpo faz, diretamente:

```sql
insert into public.cron_locks(client_id, job_name, locked_until, updated_at)
values (p_client_id, p_job_name, v_until, v_now)
on conflict (client_id, job_name) do update set ...
```

**[F]** E `public.cron_locks` **nunca recebeu `revoke` em nenhuma migration**.

**Consequência:** se o grant default incluir DML para `authenticated` — o que a seção 4 mede —, o revoke da 038 é **contornável**. Em vez de chamar a função bloqueada, escreve-se a tabela diretamente, com `locked_until` no futuro distante, para **todas** as empresas. O efeito é o mesmo que a 038 pretendeu impedir: paralisar a sincronização de dados de toda a plataforma. É indisponibilidade do pipeline, não vazamento.

**[F] Isto revela uma lacuna na consulta da §11 do `MUGO_DADOS_AUDIT.md`: ela mede apenas `SELECT`.** A consulta da seção 4 abaixo corrige isso e passa a medir `INSERT`, `UPDATE` e `DELETE`.

### 3.3 `meta_token_events` — menos grave do que a auditoria sugeriu

Correção à auditoria de ontem, que classificou esta tabela como exposição de credencial.

**[F]** O writer `_log_event` em `server/services/meta_tokens.py:175-178` remove as chaves de token antes de gravar:

```python
safe_details = dict(details or {})
safe_details.pop("access_token", None)
safe_details.pop("new_access_token", None)
```

**Classificação correta: vazamento de metadado, não de credencial.** O que se expõe é quais empresas têm conexão Meta, quando houve falha de refresh e com que frequência. Relevante, não crítico.

**Ressalva honesta:** é uma *denylist* de duas chaves, não uma allowlist. Qualquer chave nova que um chamador inclua em `details` é persistida sem filtro. **[S]** Recomenda-se inverter para allowlist, mas isso é melhoria de postura, não correção urgente.

### 3.4 As 6 tabelas da migration 042

| Estado esperado hoje | Risco |
|---|---|
| **[F]** RLS **ligado** (018) e policy `tenant_member_select` presente, **sem revoke** | **Não há vazamento entre empresas**: a policy filtra por `is_client_member(client_id)`. O risco é de postura, exatamente como a 042 descreve — um membro `viewer` lê `raw_payload` pelo browser, contornando a minimização de campos e a granularidade de papel do backend |

**Severidade: Média.** Risco real, mas contido pela policy. **A exposição ampla ocorreria se a policy fosse alterada ou o RLS desligado** — e é essa fragilidade que a 042 remove.

### 3.5 As 3 tabelas da migration 038, e `clients`

| Tabela | Risco se 038 estiver pendente | Severidade |
|---|---|---|
| **`meta_oauth_handoffs`** | **[F]** a 038 registra que **não tinha RLS nas migrations** — *"anon key lia qualquer tenant"* — e contém `encrypted_access_token` | **Alta** |
| `meta_connections` | `access_token` / `encrypted_access_token`. Confirmei que não há RLS nas migrations | **Alta** |
| `shopify_refunds` | **[F]** *"payload bruto com dados de cliente; não tinha RLS"* | **Alta** |
| `clients` | `ig_access_token` legível por membros sem a allowlist de colunas da 038 | **Alta** |

### 3.6 Existe caminho indevido entre empresas? (pergunta 5)

Resposta condicional, e a condição é medível:

| Caminho | Veredito |
|---|---|
| **Leitura cross-tenant via API** | **[F] Não.** `resolve_client_id` valida membership e não há fallback de `DEFAULT_CLIENT_ID`; a dupla verificação (`_owned`) confirma a propriedade das linhas. Nenhum IDOR encontrado |
| **Leitura cross-tenant via browser, nas 6 tabelas da 042** | **[F] Não** — a policy `tenant_member_select` filtra |
| **Leitura cross-tenant via browser, nas 4 tabelas sem RLS** | **[S] Sim, provável.** Sem RLS e sem policy, o grant default basta. `fbits_order_daily_stats` expõe receita diária de todas as empresas. **[?]** Confirmar na seção 4 |
| **Leitura de credencial, se 038 pendente** | **[S] Sim, provável**, em `meta_oauth_handoffs` e `meta_connections`. **[?]** Confirmar |
| **Escrita indevida cross-tenant** | **[S] Sim, provável** em `cron_locks` (3.2), com efeito de indisponibilidade. **[?]** Confirmar os privilégios de DML |

### 3.7 Diferenças entre schema esperado e real (pergunta 6)

**[?] Não verificável.** A consulta 4.4 mede. **[F]** A hipótese mais provável é a ausência das 18 colunas de atribuição da 044 — e o backend tolera isso por desenho: `ig_supabase._is_column_compat_error` detecta erro de coluna inexistente, e a 044 declara que *"o backend grava sem estas colunas enquanto a migration não for aplicada"*. A feature "Vendas por origem" existiria em código e devolveria cobertura zero.

---

## 4.0 Procedimento de execução

**Tempo estimado: 5 minutos.** Nenhuma das quatro consultas escreve. Nenhuma retorna dado pessoal, conteúdo de pedido, token ou valor de credencial — apenas nomes de objeto e metadados de permissão.

### Passo 1 — Abrir o projeto certo

1. Acesse `https://supabase.com/dashboard/project/rxjonbqkluzavozzmhze`.
2. **Confirme o nome do projeto no topo** e que o Reference ID em *Project Settings → General* é `rxjonbqkluzavozzmhze`.
3. Se cair em erro de permissão, troque de conta ou de organização (seção 0).

> **Pare se o ref for diferente.** Medir o banco errado é pior que não medir: produz um diagnóstico com aparência de verdade. Foi exatamente o risco do `crm_mugo`, e por isso não o usei.

### Passo 2 — Abrir o SQL Editor

Menu lateral → **SQL Editor** → **New query**.

**[S]** Se existir a opção de sessão *read-only*, use-a. Não é necessário — as consultas são `select` puro —, mas remove qualquer possibilidade de escrita acidental.

### Passo 3 — Rodar as quatro, uma por vez

Rode **separadamente**, na ordem, e guarde cada saída com o seu rótulo. São quatro resultados distintos e misturá-los dificulta o diagnóstico.

| Ordem | Consulta | Responde |
|---|---|---|
| 1ª | **4.1** RLS e privilégios | perguntas 3, 4 e 5 — e o estado de 038 e 042 |
| 2ª | **4.2** Policies | se `tenant_member_select` existe e se há policy permissiva inesperada |
| 3ª | **4.3** Colunas de `clients` e grants de função | se 038 foi aplicada; e `delete_platform_company` |
| 4ª | **4.4** Colunas de atribuição | se 044 foi aplicada — e fecha o passo 4 da investigação da Curavino |

No Supabase Studio, cole uma consulta, execute (**Ctrl/Cmd + Enter**), e use **Download CSV** ou copie a tabela.

### Passo 4 — O que me devolver

Cole as quatro saídas. Se preferir resumir, o que decide o diagnóstico é:

1. Da **4.1**: todas as linhas. São 18 tabelas e as colunas `rls_ativo`, `anon_select`, `auth_select`, `auth_insert`, `auth_update`, `auth_delete`, `policies`.
2. Da **4.3**: a linha de `delete_platform_company`, em especial `auth_exec`. **Se vier `true`, me diga primeiro** — é severidade alta e independente de todo o resto.
3. Da **4.4**: quantas linhas retornaram. Esperado 18 se a 044 está aplicada, 0 se pendente.

**Nada a mascarar antes de colar:** as consultas não retornam segredo. Se algo que pareça credencial aparecer na saída, não cole e me avise — seria achado em si.

### Passo 5 — Depois da medição

Eu comparo a saída com o estado esperado da seção 2 e fecho o diagnóstico da seção 3, substituindo cada **[S]** e **[?]** por **[F]**. Só então proponho as correções da seção 5, para a sua aprovação. **Nenhuma migration será aplicada sem o seu ok explícito.**

---

## 4. Consultas SQL a executar

**Onde:** Supabase Studio → projeto **`rxjonbqkluzavozzmhze`** (não o `crm_mugo`) → **SQL Editor** → nova query.

**Todas são somente leitura.** Nenhuma retorna dado pessoal, conteúdo de pedido, token ou valor de credencial — apenas nomes de objeto e metadados de permissão. Execute as quatro e me devolva a saída.

### 4.1 RLS e privilégios efetivos, incluindo escrita

Substitui e amplia a consulta da §11 da auditoria: aquela media só `SELECT`, o que não detectaria o risco de `cron_locks` (3.2).

```sql
select c.relname                                               as tabela,
       c.relrowsecurity                                        as rls_ativo,
       c.relforcerowsecurity                                   as rls_forcado,
       has_table_privilege('anon',          c.oid, 'SELECT')   as anon_select,
       has_table_privilege('authenticated', c.oid, 'SELECT')   as auth_select,
       has_table_privilege('authenticated', c.oid, 'INSERT')   as auth_insert,
       has_table_privilege('authenticated', c.oid, 'UPDATE')   as auth_update,
       has_table_privilege('authenticated', c.oid, 'DELETE')   as auth_delete,
       (select count(*) from pg_policies p
         where p.schemaname = 'public' and p.tablename = c.relname) as policies
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind = 'r'
  and c.relname in (
    -- As 4 descobertas na auditoria
    'cron_job_runs','cron_locks','fbits_order_daily_stats','meta_token_events',
    -- As 6 da migration 042
    'fbits_orders','fbits_order_items','shopify_customers',
    'shopify_orders','shopify_order_items','shopify_webhook_events',
    -- As 3 da migration 038, mais clients
    'meta_connections','meta_oauth_handoffs','shopify_refunds','clients',
    -- Controles: devem vir fechados
    'ai_analyses','ai_conversations','ai_messages','integration_connections'
  )
order by rls_ativo, auth_select desc, c.relname;
```

**Como ler o resultado:**

| Observação | Significado |
|---|---|
| `rls_ativo = false` **e** `auth_select = true` | **exposição de leitura confirmada** |
| `auth_insert`/`auth_update`/`auth_delete` = `true` em `cron_locks` | **escrita indevida confirmada** — o risco 3.2 é real |
| `ai_analyses` com `anon_select = false` | migration 021 aplicada. **Se vier `true`, o diagnóstico muda de escala**: o fechamento nunca funcionou em lugar algum |
| `integration_connections` com `auth_select = false` | migration 018 aplicada **com** o seu revoke — confirma a premissa da 042 |
| As 6 da 042 com `rls_ativo = true`, `auth_select = true`, `policies ≥ 1` | **042 pendente**, e o diagnóstico dela está exatamente correto |
| As 3 da 038 com `auth_select = true` | **038 pendente** |

### 4.2 Policies existentes

```sql
select tablename, policyname, cmd, permissive, roles, qual
from pg_policies
where schemaname = 'public'
order by tablename, policyname;
```

Confirma se `tenant_member_select` existe nas 6 tabelas e se alguma policy permissiva inesperada foi criada fora das migrations — o cenário que a 042 aponta como o que converteria o grant em exposição ampla.

### 4.3 Allowlist de colunas em `clients` e grants dos RPCs de lock

```sql
-- 038 aplicada => apenas id, name, trade_name para authenticated.
select table_name, column_name, privilege_type, grantee
from information_schema.column_privileges
where table_schema = 'public'
  and table_name = 'clients'
  and grantee in ('anon','authenticated')
order by grantee, column_name;

-- 038 aplicada => anon e authenticated SEM execute.
select p.proname,
       pg_get_function_identity_arguments(p.oid) as args,
       has_function_privilege('anon',          p.oid, 'EXECUTE') as anon_exec,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') as auth_exec,
       has_function_privilege('service_role',  p.oid, 'EXECUTE') as service_exec,
       p.prosecdef                                               as security_definer
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname in (
    'acquire_client_job_lock','release_client_job_lock',
    'refresh_dashboard_read_model','delete_platform_company',
    'is_client_member','is_platform_admin','create_platform_company'
  )
order by p.proname;
```

**[F]** `delete_platform_company` está aqui por um motivo específico: a migration 042 documenta que ela valida permissão com `is_platform_admin(p_actor_user_id)` — sobre um **parâmetro**, não `auth.uid()` — e que **o revoke é a única proteção efetiva** contra chamada direta. Se `auth_exec = true` nela, é achado de severidade alta e independente de todo o resto.

### 4.4 Migration 044 — colunas de atribuição e índices

```sql
select table_name, column_name
from information_schema.columns
where table_schema = 'public'
  and table_name in ('fbits_orders','shopify_orders')
  and column_name in (
    'utm_source','utm_medium','utm_campaign','utm_content','utm_term',
    'origin_channel','origin_detail','referrer_domain','attribution_source'
  )
order by table_name, column_name;

select indexname from pg_indexes
where schemaname = 'public'
  and indexname in ('idx_shopify_orders_client_origin','idx_fbits_orders_client_origin');
```

**Esperado se a 044 estiver aplicada:** 18 linhas na primeira (9 por tabela) e 2 na segunda. **Zero linhas = 044 pendente**, e isso encerra também o passo 4 da investigação da Curavino.

---

## 5. Correções necessárias

Resposta à Tarefa 2. **Nada aqui foi aplicado.** Toda correção fica condicionada à medição da seção 4.

### 5.1 Plano por tabela

| # | Alvo | Condição | Correção | Severidade |
|---|---|---|---|---|
| C1 | `meta_connections`, `meta_oauth_handoffs`, `shopify_refunds`, `clients` | 4.1/4.3 mostram abertas | **aplicar a 038** tal como está | **Alta** |
| C2 | As 6 tabelas de e-commerce | 4.1 mostra `auth_select = true` | **aplicar a 042** tal como está | **Média** |
| C3 | `fbits_order_daily_stats` | 4.1 mostra aberta | **migration nova** no padrão 038/042 | **Alta** |
| C4 | `cron_locks` | 4.1 mostra DML para `authenticated` | **migration nova** — fecha o contorno do revoke da 038 (3.2) | **Alta** |
| C5 | `cron_job_runs` | 4.1 mostra aberta | **migration nova** | **Média** |
| C6 | `meta_token_events` | 4.1 mostra aberta | **migration nova** | **Média-baixa** |
| C7 | `delete_platform_company` | 4.3 mostra `auth_exec = true` | **revogar execute** — urgente e isolado | **Alta** |
| C8 | `fbits_orders`, `shopify_orders` | 4.4 retorna zero linhas | **aplicar a 044** (aditiva, sem efeito em permissão) | Baixa |
| C9 | `meta_token_events._log_event` | independente | inverter denylist → allowlist em `meta_tokens.py:175-178` | Baixa |

**C3 a C6 cabem numa única migration nova**, no mesmo padrão idempotente das 038/042. Proponho `20261023_000045_operational_tables_lockdown.sql` — **a escrever somente após a sua aprovação e após ver a saída de 4.1**, porque a lista de tabelas a fechar depende da medição.

**Decisão a tomar antes de fechar `cron_job_runs`:** verificar se alguma tela do painel lê essa tabela pelo browser. **[F]** A auditoria constatou que o frontend usa `supabase.from()` em apenas 2 lugares — `platform_admins` e `client_memberships` (`src/App.tsx:179-180`) —, logo **[S]** o fechamento não deve afetar o painel. Confirmar com smoke test.

### 5.2 Estratégia de rollback

| Migration | Reversão | Risco de reverter |
|---|---|---|
| **038** | `grant select on public.<tabela> to authenticated` nas 3 tabelas; `grant select on public.clients to authenticated`; `grant execute` nos 2 RPCs | Reabre o problema que ela corrige. Só em incidente |
| **042** | `grant select on public.<6 tabelas> to authenticated` | A policy `tenant_member_select` permanece e volta a ser a barreira — ou seja, retorna-se ao estado atual, que é funcional |
| **044** | `alter table ... drop column if exists ...` nas 18 colunas e `drop index if exists` nos 2 | **[F]** Reversão só é segura **antes** de o backend começar a gravar nelas. Depois, dropar colunas apaga a atribuição já coletada. **Recomendação: não reverter a 044; ela é aditiva e inerte se não usada** |
| **045 (nova)** | simétrica à 042 | idem 042 |

**Por que o risco de rollback é baixo nas três:**

**[F]** Nenhuma das migrations apaga dado, altera coluna existente, recalcula KPI ou muda comportamento de integração — as próprias migrations afirmam isso, e eu confirmei lendo o SQL. **[F]** O backend usa `service_role`, que ignora RLS e recebe `grant` explícito nas migrations de fechamento. O risco está concentrado no **browser**, e a superfície é pequena: 2 chamadas diretas, em tabelas que não estão nestas listas.

**Procedimento recomendado para C1/C2:**

1. Rodar 4.1–4.4 e guardar a saída como estado *antes*.
2. Aplicar uma migration por vez, não as duas juntas.
3. Reexecutar 4.1 e comparar.
4. Smoke test do painel: login, troca de empresa, dashboard, Inteligência, Vendas por origem.
5. Suíte completa de backend e frontend.
6. Só então a próxima migration.

Aplicar separadamente importa: se o painel quebrar, você sabe **qual** grant era dependido indevidamente.

---

## 6. Plano para deixar a suíte verde

Resposta à Tarefa 3. **Tudo nesta seção foi executado e medido**, num worktree isolado em `badcb97`. Nada na sua árvore foi alterado.

### 6.1 Diagnóstico das 3 falhas e do erro

| # | Problema | Classificação | Causa raiz |
|---|---|---|---|
| 1 | `test_progressive_context::test_complete_orders_allow_calculable_zero_or_positive_recurrence` | **Problema de teste** | orçamento de consultas desatualizado |
| 2 | `test_progressive_context::test_uncovered_period_does_not_turn_known_historical_customers_into_zero` | **Problema de teste** | idem |
| 3 | `test_intelligence_reports` (ImportError) | **Problema de ambiente** | `pypdf` importado pelo teste e **não declarado** no `requirements.txt` |
| 4 | `test_viewer_release_readiness::test_no_mutation_route_lacks_a_role_guard` | **Comportamento esperado que precisa de documentação** | decisão de produto não registrada no `EXEMPT` |

### 6.2 As duas falhas de `test_progressive_context`, diagnosticadas

A mensagem (`AssertionError: 6 != 5`) é enganosa e eu instrumentei o código para achar a causa real.

**[F]** A asserção é `self.assertEqual(query.await_count, 5 if detailed else 4)`. Instrumentando `calculate_intelligence_snapshot` com `include_commerce_details=True`, as 6 leituras são:

```
1. dashboard_daily_metrics      4. integration_connections
2. dashboard_source_snapshots   5. client_business_context
3. ig_media                     6. campaign_daily_stats   <-- a sexta
```

**[F] A sexta chamada não é repetição: é uma tabela nova, `campaign_daily_stats`.** Ela vem de `_campaign_analysis_context` (`intelligence.py:788-831`), funcionalidade de contexto de campanha adicionada depois que o teste foi escrito — coerente com o commit `117fd8d` *"restore campaign context and temporal recovery"*. **O código de produção está correto; o teste ficou atrás.**

**[F] Por que a mensagem é confusa, e isto é um achado secundário:** o mock do teste chamaria `self.fail('Leitura pesada inesperada: campaign_daily_stats')`, mas `_campaign_analysis_context` envolve a leitura num `except Exception:` largo (`intelligence.py:830`) que devolve `status: "unavailable"`. O `AssertionError` do `self.fail` é **engolido** junto com os erros de I/O. A degradação graciosa é comportamento de produto **correto** — *"No partial page is published after a read failure"* — mas tem o efeito colateral de neutralizar o guard do teste, que nunca consegue falhar em voz alta.

### 6.3 Correção mínima, validada

Duas linhas em `server/tests/test_progressive_context.py`. **Nenhuma alteração em código de produção.**

```python
# 1) campaign_daily_stats passa a ser leitura esperada no modo detalhado
if table == 'campaign_daily_stats' and detailed: return []

# 2) orçamento corrigido: detailed soma ig_media + campaign_daily_stats
self.assertEqual(query.await_count, 6 if detailed else 4)
```

**[F] Resultado medido:** `Ran 8 tests — OK`.

**[S] Melhoria recomendada, não obrigatória:** trocar o `self.fail` dentro do mock por acumulação numa lista, com asserção **após** o `with`. Assim o guard contra "leitura pesada inesperada" volta a funcionar, em vez de ser silenciado pelo `except Exception`. Sem isso, a próxima leitura inesperada reaparecerá como outro `N != M` obscuro.

### 6.4 `pypdf` e `reportlab` — e um achado que estava escondido

Instalei as duas de forma **isolada** (`pip install --target` num diretório do scratchpad, usado via `PYTHONPATH`). **Nada global, nada na sua `.venv-1`, nada em produção.**

**[F]** Com `pypdf` disponível, o `ImportError` desaparece e o módulo carrega — mas surgem **6 erros novos**, todos `ModuleNotFoundError: No module named 'reportlab'`, em `intelligence_reports.py:33`.

**[F]** `reportlab==4.5.1` **está** declarado no `requirements.txt`. Logo existe em produção e falta apenas na `.venv-1` local.

**[F]** Com ambas disponíveis: **os 7 testes de PDF passam.**

**Correção à auditoria de ontem.** Eu havia classificado a geração de PDF como *"implementada sem homologação suficiente"* porque os testes não executavam. **Isso estava errado em substância:** a cobertura existe e passa. O que faltava era ambiente local. A classificação correta é **implementada e testada**, com a ressalva de que a suíte não roda num ambiente limpo sem `pypdf` declarado.

### 6.5 A falha do meta-teste de guard — decisão sua

**[F]** Persiste, e aponta as mesmas 4 rotas:

```
intelligence.intelligence_rename_conversation  (PATCH)
intelligence.intelligence_delete_conversation  (DELETE)
intelligence.intelligence_create_conversation  (POST)
intelligence.intelligence_resume_conversation  (POST)
```

**[F]** Causa: usam `_context()` (`routes/intelligence.py:31-39`), que valida membership mas **não papel** — um `viewer` gere as próprias conversas.

**[F] Não é vulnerabilidade:** `resolve_client_id` garante o escopo da empresa e `_scope` filtra por `client_id` **e** `user_id`, com reverificação `_owned`. Sem IDOR, sem cross-tenant, e o dado afetado é do próprio usuário.

**É a única das quatro que eu não posso resolver sozinho, porque é decisão de produto.** Duas opções:

| Opção | Ação | Quando faz sentido |
|---|---|---|
| **A** | Adicionar as 4 ao `EXEMPT` com motivo escrito | Se gerir as próprias conversas é permitido a qualquer membro — **[F]** coerente com `intelligence_generate` e `intelligence_ask`, já isentos pelo mesmo raciocínio |
| **B** | Trocar `_context` por `require_client_role` nas 4 | Se um `viewer` não deve criar nem apagar conversas |

**[S] Recomendo A**, por consistência: o mesmo teste já isenta a geração de análise — que **custa dinheiro** — com a justificativa de que o custo é contido no servidor e não por papel. Recusar a um viewer renomear a própria conversa, permitindo-lhe gerar uma análise paga, seria incoerente.

### 6.5-bis Correções aplicadas em 2026-10-23

**Status: aplicadas e medidas.** Branch `fix/phase0-test-readiness`, commit `a325151`, num worktree isolado. **Sem push, sem merge.** **[F] Nenhuma linha de código de produção foi alterada** — as 15 mudanças estão todas em `server/tests/`, mais `server/requirements-dev.txt`.

| # | Mudança | Arquivos |
|---|---|---|
| 1 | Orçamento de consultas corrigido (6.3) | `test_progressive_context.py` |
| 2 | **Opção A do item 6.5**: as 4 rotas de conversa no `EXEMPT`, com o motivo e o mecanismo de isolamento documentados | `test_viewer_release_readiness.py` |
| 3 | `modules()` passa a **varrer `routes/`**; `goals.writer()` registrado em `ROLE_GUARDS` | `test_viewer_release_readiness.py` |
| 4 | `_bootstrap.py` centraliza o `sys.path` das duas convenções; importado pelos 12 módulos que não o faziam | `_bootstrap.py` + 12 módulos |
| 5 | `pypdf==6.21.2` declarado | `server/requirements-dev.txt` (novo) |

#### A varredura encontrou o que a lista literal escondia

**[F]** Trocar a lista literal por varredura fez surgirem **3 rotas de mutação que nunca haviam sido verificadas**, em `goals` — módulo ausente da lista dos 14:

```
goals.create_goal  (POST)
goals.edit_goal    (PUT)
goals.delete_goal  (DELETE)
```

**[F] Investigadas: são falso positivo, e estão corretas.** `server/routes/goals.py:36-37` define um helper local:

```python
async def writer(cid, auth):
    return await require_client_role(cid, auth, allowed_roles=("agency_admin", "client_admin"))
```

As três chamam `await writer(...)`, rebindam `cid` a partir do guard e filtram por `client_id` — o padrão correto. O teste apenas não conhecia o helper, como já conhecia `_manage_context` e `_mutation_context`. Registrei `"await writer("` em `ROLE_GUARDS`, com a assinatura da chamada em vez da palavra isolada, para não casar por acidente no corpo de outra rota.

**O valor aqui não é o achado, é o mecanismo.** `goals` e `sales_origin` estavam fora da auditoria do meta-teste; agora nenhum módulo novo escapa. **[F]** A asserção `assertIn("sales_origin", discovered)` protege a própria varredura contra regressão silenciosa.

#### Duas abordagens testadas e rejeitadas, pela evidência

Registro porque poupam o tempo de quem tentar o caminho óbvio:

| Tentativa | Resultado medido |
|---|---|
| **`conftest.py`** com o `sys.path.insert` | **Não funciona.** `conftest.py` é convenção do **pytest**; `unittest discover` não o carrega. O teste isolado continuou falhando. Era a minha recomendação em 6.7 e **estava errada** |
| **`-t server` + `server/tests/__init__.py`** | **Pior que o problema.** Resolve o isolamento, mas transformar `tests` em pacote quebra os imports irmãos (ex.: `cron_fixtures`): **8 módulos com erro e a contagem caiu de 1689 para 1536** |

A solução adotada — `_bootstrap.py` importado explicitamente — não tem mágica, é consistente com o `sys.path.insert` que 78 módulos já faziam, e funciona nos dois modos de execução.

**[F] Detalhe que custou uma iteração:** nos 3 módulos com `from __future__ import annotations`, o import tem de vir **depois** dessa linha, ou o Python falha com `SyntaxError: from __future__ imports must occur at the beginning of the file`.

#### Medição final

**[F]** Com `pypdf` e `reportlab` disponíveis:

| Modo de execução | Antes | Depois |
|---|---|---|
| Da raiz | 1682 testes, 3 falhas, 1 erro | **1689, 0, 0** |
| De dentro de `server/` | 1528 testes | **1689, 0, 0** |
| `test_tenant_isolation` isolado | `ModuleNotFoundError` | **18 testes, OK** |
| `test_oauth_security` isolado | `ModuleNotFoundError` | **44 testes, OK** |
| `test_intelligence_reports` isolado | `ModuleNotFoundError` | **8 testes, OK** |
| Frontend | 748/748 | **748/748**, inalterado |

**[F] A suíte está verde, com a mesma contagem nos dois diretórios, e a discrepância de 154 testes acabou.** `test_tenant_isolation` e `test_oauth_security` — os dois módulos mais críticos de segurança — deixaram de desaparecer em silêncio.

#### O que falta nesta trilha

- [ ] Revisar e aprovar a branch `fix/phase0-test-readiness` (commit `a325151`)
- [ ] `pip install -r server/requirements-dev.txt` no ambiente local de desenvolvimento
- [ ] `reportlab` na venv local — **[F]** já está no `requirements.txt` de produção; falta só localmente
- [ ] **[S]** Remover, sem pressa, os 78 `sys.path.insert` agora redundantes
- [ ] **[S]** Trocar o `self.fail` dentro do mock de `test_progressive_context` por acumulação e asserção após o `with`, para que o guard de "leitura pesada inesperada" volte a falhar em voz alta em vez de ser engolido pelo `except Exception` de `intelligence.py:830`

### 6.6 Baseline antes e depois

| Cenário | Testes | Falhas | Erros |
|---|---|---|---|
| **[F]** `origin/main`, ambiente da auditoria | 1682 | 3 | 1 |
| **[F]** + correção 6.3 + `pypdf` + `reportlab` | 1689 | 1 | 0 |
| **[F]** + opção A + varredura + `_bootstrap` (commit `a325151`) | **1689** | **0** | **0** |

**[F] Confirmado por execução: a suíte está verde.** Nenhuma linha de produção foi alterada.

**[F]** Frontend reexecutado sobre a branch: **748/748 em 108 arquivos**, inalterado.

### 6.7 Achado estrutural: a suíte não é isolável por módulo

**[F]** 78 dos 94 módulos de teste fazem `sys.path.insert` por conta própria. **16 não fazem**, e **não existe `conftest.py`** em `server/` nem em `server/tests/`.

**[F]** Consequência medida: `test_intelligence_reports.py` importa `from services import ...` sem inserir o path. Rodar **esse arquivo isolado falha** com `ModuleNotFoundError: No module named 'services'`. Na suíte completa funciona, porque algum módulo anterior em ordem alfabética já inseriu o path.

**A suíte depende da ordem de carga.** Funciona no CI, que roda tudo, e falha exatamente quando um desenvolvedor roda um arquivo só — que é o modo normal de trabalhar.

**Correção aplicada:** `server/tests/_bootstrap.py`, importado explicitamente pelos 12 módulos. Ver 6.5-bis.

**Duas correções desta seção estavam erradas e foram retiradas:**

- **`conftest.py` não resolve.** É convenção do pytest; `unittest discover` não o lê. Testado: o arquivo isolado continuou falhando.
- **`__init__.py` piora.** Transformar `tests` em pacote quebra os imports irmãos: 8 módulos com erro, contagem de 1689 para 1536.

**[F] Correção de número:** são **12** módulos `test_*.py` sem o bootstrap, não 16. A contagem anterior incluía arquivos de `server/tests/` que não são módulos de teste (como `cron_fixtures.py`).

**[F]** Isto também explica a discrepância 1682 vs 1528 da auditoria: rodar de dentro de `server/` perde 7 módulos (154 testes), incluindo `test_tenant_isolation` e `test_oauth_security`.

---

## 7. Checklist de homologação

### 7.1 Banco — bloqueante

- [x] **Identificar o projeto Supabase do Mugô Dados** → **`rxjonbqkluzavozzmhze`** (seção 0)
- [ ] Confirmar no Render que `SUPABASE_URL` aponta para esse ref (sem revelar chaves)
- [ ] Executar 4.1 e anexar a saída
- [ ] Executar 4.2 e anexar a saída
- [ ] Executar 4.3 e anexar a saída
- [ ] Executar 4.4 e anexar a saída
- [ ] Controle: `ai_analyses` com `anon_select = false`
- [ ] Controle: `integration_connections` com `auth_select = false`
- [ ] Decidir sobre C1–C8 com base na medição
- [ ] Verificar `auth_exec` em `delete_platform_company` (C7 — independente e urgente se positivo)
- [ ] Registrar o estado medido neste repositório

### 7.2 Aplicação das migrations — só após 7.1

- [ ] Saída de 4.1 guardada como estado *antes*
- [ ] 038 aplicada isoladamente, com aprovação explícita
- [ ] 4.1 reexecutada e comparada
- [ ] Smoke: login, troca de empresa, dashboard, Inteligência, Vendas por origem
- [ ] Suíte backend e frontend verdes
- [ ] 042 aplicada isoladamente, mesmo ciclo
- [ ] 044 aplicada, mesmo ciclo
- [ ] Migration 045 (C3–C6) escrita, revisada e aplicada
- [ ] Nenhuma linha de 4.1 com `rls_ativo = false` **e** `auth_select = true` sem justificativa escrita
- [ ] Nenhuma linha com DML para `authenticated` sem justificativa escrita

### 7.3 Suíte — não bloqueante para 7.1, bloqueante para o MCP

- [x] Correção 6.3 aplicada e medida
- [x] `pypdf` declarado em `server/requirements-dev.txt`
- [x] Decisão 6.5 tomada (**opção A**) e registrada no `EXEMPT`, com o mecanismo de isolamento documentado
- [x] Descoberta de módulos de rota por varredura; `goals` e `sales_origin` agora cobertos
- [x] Execução isolada resolvida (`_bootstrap.py`) — `conftest.py` e `__init__.py` testados e descartados
- [x] Suíte verde da raiz **e** de dentro de `server/`, **com a mesma contagem: 1689**
- [x] Arquivos isolados rodam sozinhos, inclusive `test_tenant_isolation` e `test_oauth_security`
- [x] Frontend verde: 748/748
- [ ] Revisar e aprovar a branch `fix/phase0-test-readiness` (`a325151`)
- [ ] `reportlab` instalado na venv local de desenvolvimento

### 7.4 Postura, baixo custo

- [ ] `APP_ENV` default invertido: ausência = produção
- [ ] `sb_rpc` morto removido (`ig_supabase.py:252`)
- [ ] `modules()` do meta-teste passa a varrer `routes/` em vez de lista literal
- [ ] `_log_event` convertido para allowlist (C9)
- [ ] `graphify update .` — **[F]** o grafo não contém o PR #14

---

## 8. Critérios para liberar o MCP v0.1

Seis critérios. **Todos verificáveis**, nenhum subjetivo.

| # | Critério | Por quê |
|---|---|---|
| **1** | **Estado de RLS e grants medido e registrado** para as 18 tabelas de 4.1, sem linha aberta não justificada | O MCP multiplica os caminhos de leitura de dados de tenant. Ampliar acesso antes de saber se o fechamento está em vigor é a ordem errada |
| **2** | **`cron_locks` fechada para DML** de `anon`/`authenticated` | Enquanto o contorno de 3.2 existir, o pipeline de dados é interrompível por qualquer usuário autenticado — e o MCP depende de dado sincronizado |
| **3** | **`delete_platform_company` sem `execute` para `anon`/`authenticated`** | **[F]** O controle de acesso dela confia num parâmetro; o revoke é a única proteção. É também a regra que o MCP herda: nenhuma ferramenta pode expor RPC com acesso por argumento |
| **4** | ~~**Suíte verde**, da raiz e de `server/`, com a mesma contagem, e um arquivo isolado rodando~~ → **ATENDIDO** em `a325151`: 1689/0/0 nos dois diretórios, isolados OK. Resta só aprovar a branch | **[F]** A extração em `calculate_intelligence_snapshot` (1460 linhas) é pré-requisito do MCP. Fazê-la sem rede de teste confiável é imprudente |
| **5** | **Instrumentação de custo de IA em produção** — tokens, custo e latência por empresa | **[F]** Hoje é zero. O MCP multiplica chamadas; sem medição, o gasto fica invisível e o SaaS não é precificável |
| **6** | **Decisão 6.5 registrada** | Suíte vermelha normalizada mascara a próxima falha real — e o MCP vai introduzir rotas de mutação (emissão e revogação de token) que dependem exatamente desse meta-teste |

**Critérios 1, 2 e 3 dependem de você** (acesso ao banco). **4 e 6** estão a duas linhas e uma decisão. **5** é a trilha 1B da Fase 1 do roadmap.

---

## 9. Resumo

**O que ficou provado:**

- **[F]** As três migrations se declaram não aplicadas, mas **isso é declaração do autor, não medição**. O estado real continua desconhecido e a seção 4 é o que o resolve.
- **[F]** As 4 tabelas descobertas não têm RLS, policy, revoke ou grant em **nenhuma** das 44 migrations, e **não são cobertas** por 038 nem 042.
- **[F]** `fbits_order_daily_stats` contém receita diária por empresa — a exposição de leitura mais sensível comercialmente.
- **[F]** `cron_locks` é um **caminho de escrita**: a 038 fechou o RPC de lock, mas a função é `security definer` e escreve a tabela direto, e a tabela nunca foi fechada. O revoke é contornável.
- **[F]** `meta_token_events` **não** vaza token — o writer remove as chaves. Metadado, não credencial. Correção à auditoria de ontem.
- **[F]** A consulta da §11 da auditoria media só `SELECT` e não detectaria 3.2. Corrigida em 4.1.
- **[F]** As 2 falhas de `progressive_context` são **problema de teste**: a 6ª consulta é `campaign_daily_stats`, de uma feature nova. Correção de 2 linhas, **validada: 8/8**.
- **[F]** O erro de `pypdf` escondia 6 erros de `reportlab`. Com ambiente completo, **os 7 testes de PDF passam** — a geração de PDF **está** homologada, ao contrário do que a auditoria concluiu.
- **[F]** A suíte vai a **1689 testes, 1 falha, 0 erros** com duas linhas e duas dependências de ambiente. A última falha é decisão de produto.
- **[F]** A suíte depende de ordem de carga: 16 módulos sem `sys.path.insert` e sem `conftest.py`. Um arquivo isolado não roda.

**Acrescentado em 2026-10-23:**

- **[F]** Projeto de produção identificado: **`rxjonbqkluzavozzmhze`**. Não é o `crm_mugo` e não está na conta em que o CLI está autenticado. O ref veio do bundle público do frontend, de onde extraí **só o hostname**.
- **[F]** Nenhum segredo nem URL de Supabase jamais foi commitado neste repositório, em todo o histórico. Postura correta.
- **[F]** Suíte **verde**: 1689 testes, 0 falhas, 0 erros, **mesma contagem da raiz e de dentro de `server/`**. Arquivos isolados rodam, inclusive os dois críticos de segurança.
- **[F]** A varredura de rotas revelou 3 mutações nunca auditadas em `goals` — **investigadas e corretas** (helper `writer()` aplica `require_client_role`). O ganho é o mecanismo: módulo novo não escapa mais.
- **[F]** Duas correções que eu havia recomendado estavam erradas e foram descartadas por teste: `conftest.py` (não funciona com `unittest`) e `__init__.py` (quebra 8 módulos).
- **[F]** Zero linhas de produção alteradas. Branch `fix/phase0-test-readiness`, commit `a325151`, sem push.

**O que depende de você:**

1. **Rodar as quatro consultas da seção 4** no projeto `rxjonbqkluzavozzmhze`, seguindo o procedimento da seção 4.0.
2. Revisar e aprovar a branch `fix/phase0-test-readiness`.
3. Autorizar as correções de 5.1, após ver a medição.

**Nenhuma migration executada. Nenhum dado alterado. Nenhum deploy, push ou merge. Aguardo sua aprovação.**
