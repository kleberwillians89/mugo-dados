# Refresh de providers — relatório de release

Data: 05/10/2026. Workspace autorizado: `/Users/k/Desktop/mugo-dados`.

**GO técnico local para revisão da release.** A execução final passou em frontend, backend, lint, typecheck, build e diff-check. Nenhum commit, push, deploy, migration ou alteração em banco remoto foi executado.

## Arquitetura auditada — CONFIRMADO

| Provider | Arquivos e símbolos reais | Arquitetura encontrada e atualização resultante |
| --- | --- | --- |
| FBITS | `fbits_connections.sync_fbits_connection`, `fbits_reporting.build_fbits_summary`, `fbits_official_kpis.fetch_official_kpis`, `Ecommerce.FbitsCommerce` | Pedidos, itens e agregados persistidos por tenant. Histórico inicial em janelas e incremental com sobreposição. Receita/pedidos/ticket oficiais vêm de `/dashboard/faturamento`, com cache existente e fallback identificado. A fachada aguarda o sync terminar antes da releitura; evita tratar o antigo 202 de agendamento como conclusão. |
| Shopify | `shopify_oauth.sync_shopify_connection`, `resolve_shopify_reconciliation_since`, `Shopify.onRefreshData` | Dashboard principal usa read model; relatórios detalhados usam persistência local. Refresh resolve a loja persistida, respeita `selected_for_reporting` e executa reconciliação incremental a partir do watermark, com fallback de 60 dias. Não aceita domínio ou conexão enviados pelo browser. |
| Meta | `Dashboard.onRefresh`, `instagram_sync.sync_instagram_for_client`, `ads_sync.sync_ads_for_client_period` | Instagram orgânico e Meta Ads usam conexões operacionais de `meta_connections`. O refresh anterior também disparava Shopify/Google. Agora chama somente Meta. Instagram mantém a rotina existente de atualização orgânica atual; Ads usa o período selecionado. O modo `persisted_only` proíbe fallback de token global e descoberta de identidade ausente. |
| Google | `GoogleAnalytics.handleRefresh`, `ga4_sync.sync_ga4_for_period`, `google_ads.sync_google_ads` | GA4 e Google Ads usam conexões persistidas separadas. Conta/property e tokens são resolvidos no backend. As fontes executam independentemente; se uma falhar, a resposta é sanitizada e a tela mantém a leitura anterior. GA4 aceita `connection_id` no sync real e usa lock por tenant/property; Ads resolve a conexão antes de adquirir o lock quando o caller legado omite o ID. |

Evidência de autorização anterior: os handlers administrativos usam `require_client_role`; os botões dependiam de `canSync`. A leitura de Ecommerce já usava `useActiveEcommerceProvider` com `/api/connections`. Liberar somente o botão não autorizaria viewer no backend.

## Endpoints e autorização

Novo endpoint usado pelas três telas:

`POST /api/clients/{client_id}/data-refresh/{provider}`

Providers permitidos: `fbits`, `shopify`, `meta`, `google`. Corpo: somente `start` e `end`, como datas válidas, intervalo inclusivo de até 366 dias. Campos extras e query parameters são recusados. Credenciais, tokens, IDs de conta/business/property/conexão e domínio de loja não entram nesse contrato.

`refresh_client_provider` chama `require_client_read`, que resolve membership do tenant antes de executar trabalho. Viewer do próprio tenant é permitido; outro tenant é 403. Admin continua autorizado segundo as regras existentes. Resposta de sucesso contém somente `ok`, `client_id` e `provider`; não repassa o payload das integrações.

As rotas administrativas anteriores continuam protegidas: FBITS `/api/clients/{client_id}/fbits/sync` e `/api/fbits/sync`; Shopify `/api/oauth/shopify/{connection_id}/sync`; Meta `/api/ig/refresh_all`, `/api/ads/sync` e `/api/clients/{client_id}/meta-ads/sync`; Google `/api/google/ga4/sync`, `/api/google/ads/sync` e `/api/oauth/google/{connection_id}/sync`. Conectar, desconectar, selecionar ativos, administrar empresas/usuários e executar OAuth não foram liberados para viewer. Nenhum arquivo de rotas OAuth foi alterado.

Inteligência não foi alterada. A suíte de readiness continua cobrindo geração permitida para membership e `/ask` fechado para viewer. A fachada de providers não chama geração de análise nem o provider OpenAI.

## Cooldown e concorrência

- `runExclusiveSync` deduplica chamadas concorrentes no browser por tenant/provider.
- A fachada usa `guarded_sync` e a RPC existente de locks do banco; não cria tabela ou mecanismo paralelo.
- Uma lease separada `refresh_cooldown:{provider}` aplica 60 segundos por tenant/provider. Ela expira naturalmente e não é liberada quando a tentativa termina, inclusive em falha.
- Os syncs preservam seus locks próprios. GA4 foi alinhado por property persistida; Google Ads por conexão persistida, inclusive nas entradas legadas.
- FBITS para no primeiro 429. Persiste `metadata.rate_limit_until` e verifica o bloqueio antes de ler token/chamar provider, inclusive novamente dentro do lock.
- `Retry-After` aceita segundos e HTTP-date. A espera respeita no mínimo 60 segundos; sem header usa uma hora, de forma conservadora. A fachada devolve `Retry-After` em 429.
- Os KPIs oficiais também verificam/persistem o bloqueio do tenant, para não contorná-lo por outra leitura/período. A invalidação de cache mantém o backoff de 429.

Não foi criado polling nem sync externo automático no carregamento das páginas. A consulta oficial FBITS que já existia no carregamento foi preservada.

## Last-known-good e freshness

Os botões usam a classe de ação da Inteligência e o formatter existente `formatFreshness`. Durante o sync, exibem `Atualizando...` e ficam desabilitados. Não limpam o snapshot nem trocam cards/gráficos por skeleton.

A releitura ocorre após sucesso. Falhas mantêm os dados anteriores e mostram aviso. O hook de GA4 preserva canais/campanhas quando a leitura detalhada falha; o freshness vem de `sources.last_success_at`, não do horário de fetch. Shopify e Meta usam o último sucesso persistido no read model. FBITS usa `metadata.last_success_at`/`last_sync_at`, que o sync avança no sucesso.

Se a leitura oficial FBITS falhar após o sync, um fallback não substitui KPIs oficiais já carregados e o freshness da tela não avança. Respostas de outro tenant são descartadas antes de gravar o cache. Trocar a empresa durante a espera interrompe a releitura do refresh anterior.

## Testes executados

Execução final: `PATH=/tmp/mugo-refresh-venv/bin:$PATH npm test`.

- Frontend completo: **562 testes, 82 arquivos, todos passaram**.
- Backend completo: **1.297 testes, todos passaram, nenhum ignorado**.
- `npm run lint`: passou, sem avisos.
- `npm run typecheck`: passou.
- `npm run build`: passou.
- `git diff --check`, `git status --short` e revisão de `git diff`: executados.

O Python padrão não tinha `httpx` e não iniciou os testes. As dependências declaradas em `server/requirements.txt` foram instaladas em um venv temporário com Python 3.13; a validação final usa esse ambiente. Nenhuma dependência do repositório foi alterada.

As famílias solicitadas também foram executadas por discovery: viewer release readiness, integrations, Meta, Google, FBITS, Shopify, intelligence, client_access, customers, tenant isolation e provider refresh. Um teste de readiness apontava para o handler inexistente `platform_company_delete`; foi corrigido para `platform_delete_company`, eliminando o skip e testando a recusa real de viewer.

Cobertura nova/revisada:

| Requisito | Evidência executável |
| --- | --- |
| Viewer Curavino, admin e cross-tenant | `server/tests/test_provider_refresh.py`: `test_viewer_curavino_can_refresh_each_allowed_provider`, `test_admin_still_can_refresh`, `test_cross_tenant_is_403_before_sync` |
| IDs/credenciais recusados e payload sanitizado | Mesmo arquivo: `test_credentials_and_arbitrary_assets_are_rejected`, `test_fbits_only_and_response_never_contains_credentials` |
| Cooldown e clique concorrente | Mesmo arquivo: `test_server_cooldown_prevents_all_external_work`, `test_two_requests_never_start_two_syncs`, `test_persisted_cooldown_blocks_before_token_or_provider`; teste existente de 429 em `test_fbits_multitenant.py` agora também verifica a persistência e ausência de nova chamada |
| Shopify, Meta e Google persistidos | Mesmo arquivo: `test_shopify_resolves_persisted_selection_without_browser_id`, `test_meta_syncs_only_persisted_meta_sources_and_sanitizes_failure`, `test_google_uses_persisted_property_and_ads_with_independent_syncs` |
| Sem rediscovery/token global Meta | Mesmo arquivo: `test_refresh_without_instagram_identity_never_discovers_or_syncs`, `test_restricted_token_never_uses_global_fallback`, `test_restricted_instagram_missing_identity_never_reads_legacy_or_discovers` |
| Contrato real e locks de Google | Mesmo arquivo: `test_ga4_real_sync_accepts_connection_and_shares_lock_with_legacy_callers`, `test_ads_legacy_request_resolves_persisted_connection_before_lock` |
| Last-known-good, freshness, cards/gráficos e tenant na UI | `Ecommerce.test.tsx`, `GoogleAnalytics.refresh.test.tsx`, `Dashboard.channelReport.test.tsx`, `Shopify.test.tsx`, `useDashboardFbits.test.tsx`, `useDashboardGa4.test.tsx` |
| Endpoint sem OAuth/IA e corpo mínimo | `src/app/api.ecommerceSync.test.ts`: `refresh envia somente período à fachada do tenant, sem OAuth, IDs ou IA`; os testes da fachada também instalam um spy em `intelligence._call_provider`, que não pode ser chamado |
| Administração continua fechada | `test_viewer_release_readiness.py` e `test_provider_refresh.py`: `test_viewer_still_cannot_read_admin_integrations` |

Os testes usam tenants, memberships, tokens e respostas **sintéticos**; não exercitam credenciais reais da Curavino.

Mutation testing dirigido: `python server/tests/run_provider_refresh_mutations.py`, executado no venv temporário. **11/11 mutações detectadas**: remover membership; permitir campos extras; ampliar allowlist; remover lock; remover cooldown; ignorar cooldown FBITS; usar token global Meta; redescobrir identidade Instagram; quebrar o contrato real de GA4; perder o lock canônico Ads; vazar payload privado. As mutações são aplicadas somente em cópias temporárias dos fontes.

## Riscos e limites

- O novo frontend depende da fachada no backend. Não houve publicação de nenhum dos dois nesta execução.
- Os locks mantêm a política de lease/TTL existente (900 segundos no Shopify e 1.800 nos demais syncs/fachada). As provas de concorrência cobrem exclusão durante a lease; execução que ultrapasse o TTL exige avaliação operacional do mecanismo existente.
- Em falha parcial, uma fonte pode já ter persistido linhas. A tela atual conserva o snapshot anterior; uma leitura posterior pode mostrar o dado persistido. Não foi criada transação distribuída entre providers.
- A projeção do read model e a seleção prévia de uma conexão válida continuam pré-requisitos. Ambiguidade/configuração ausente gera recusa, sem seleção arbitrária ou reabertura de OAuth.
- A verificação de UI foi por testes DOM; não foi executado smoke visual autenticado em ambiente real.

**NÃO CONFIRMADO NO CÓDIGO.** Funcionamento com a conexão real da Curavino, tokens reais, limites reais dos providers e timeouts da infraestrutura publicada não foi validado por esta execução local.

Decisão: **GO técnico local; NO-GO para afirmar homologação de produção sem smoke no ambiente real.**

## Arquivos alterados nesta tarefa

- `server/routes/integrations.py`
- `server/services/ads_sync.py`
- `server/services/fbits_client.py`
- `server/services/fbits_connections.py`
- `server/services/fbits_official_kpis.py`
- `server/services/ga4_sync.py`
- `server/services/google_ads.py`
- `server/services/instagram_sync.py`
- `server/services/meta_tokens.py`
- `server/tests/test_fbits_multitenant.py`
- `server/tests/test_fbits_official_kpis.py`
- `server/tests/test_viewer_release_readiness.py`
- `src/app/api.ecommerceSync.test.ts`
- `src/app/api.ts`
- `src/hooks/dashboard/useActiveEcommerceProvider.ts`
- `src/hooks/dashboard/useDashboardFbits.test.tsx`
- `src/hooks/dashboard/useDashboardFbits.ts`
- `src/hooks/dashboard/useDashboardGa4.test.tsx`
- `src/hooks/dashboard/useDashboardGa4.ts`
- `src/pages/Dashboard.channelReport.test.tsx`
- `src/pages/Dashboard.refreshContract.test.ts`
- `src/pages/Dashboard.tsx`
- `src/pages/Ecommerce.test.tsx`
- `src/pages/Ecommerce.tsx`
- `src/pages/GoogleAnalytics.refresh.test.tsx`
- `src/pages/GoogleAnalytics.test.tsx`
- `src/pages/GoogleAnalytics.tsx`
- `src/pages/Shopify.test.tsx`
- `src/pages/Shopify.tsx`
- `server/services/provider_refresh.py`
- `server/tests/test_provider_refresh.py`
- `server/tests/run_provider_refresh_mutations.py`
- `docs/provider-refresh-release.md`

Alterações locais anteriores foram preservadas. Os arquivos excluídos da lista acima já estavam modificados antes da tarefa; `.opencode/` e `AGENTS.md` também já existiam como não rastreados.
