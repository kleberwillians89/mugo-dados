# Metas do Cliente — revisão local

## 1. Arquitetura encontrada e preservada

CONFIRMADO
- Arquivo: `server/services/tenant.py`; símbolos: `require_client_read`, `require_client_role`.
- Evidência: leitura resolve tenant autorizado; escrita exige perfil administrativo e mantém aliases legados `owner`/`admin`, agência e plataforma.
- Conclusão: as novas rotas reutilizam a autorização existente, sem modificar autenticação.

CONFIRMADO
- Arquivos: `server/services/commerce_context.py`, `server/services/fbits_reporting.py`.
- Símbolos: `select_commerce_connection`, `_valid_metrics`.
- Evidência: seleção existente dá prioridade a FBITS entre conexões ativas; agregação persistida reconhece situações configuradas e exclui pedidos explicitamente inválidos.
- Conclusão: Metas reutiliza esses helpers puros. O resultado derivado FBITS é identificado como **não sendo o KPI oficial**.

CONFIRMADO
- Arquivo: `supabase/migrations/20260811_000026_dashboard_read_model.sql` e migrations seguintes de métricas Shopify.
- Evidência: `dashboard_daily_metrics` armazena as colunas comerciais, sociais e pagas utilizadas pelo resolver.
- Conclusão: não foi criado outro read model nem um mecanismo de refresh.

Adições: `server/routes/goals.py` fornece GET/POST em `/api/clients/{client_id}/goals` e PUT/DELETE em `/{goal_id}`. `server/services/goals.py` concentra resolução e cálculo. Não há chamada a providers ou IA nesses caminhos. GET faz consultas ao armazenamento persistido. A integração futura com Intelligence pode consumir o objeto calculado; o fluxo atual da IA permanece intacto.

## 2. Migration

`supabase/migrations/20261007_000043_client_goals.sql`, criada localmente e **não aplicada**.

Tabela `client_goals`: UUID, tenant text com FK/cascade para `clients`, indicador allowlist, nome, objetivo positivo e finito limitado a 10¹⁵, datas de até 366 dias inclusivos, timestamps e autor. Índice tenant/período; trigger existente `set_updated_at`; RLS de leitura via `is_client_member`. Browser autenticado recebe somente SELECT; escrita exclusivamente pelo backend/service role. Não modifica RLS de outras tabelas. O nome segue a sequência após a migration 000042 já existente, cuja versão é 20261006.

## 3–4. Métricas suportadas e origem

| Indicador | Origem e definição | Restrição |
| --- | --- | --- |
| revenue | FBITS: soma de `fbits_orders.total_value` reconhecidos por situações; Shopify: `shopify_net_revenue` | Ecommerce ativo escolhido pela regra existente; ausência de situações FBITS ou dados torna indisponível |
| orders | FBITS: contagem reconhecida; Shopify: `shopify_orders` | Mesma seleção comercial |
| average_ticket | Receita / pedidos; helper persistido FBITS ou agregado Shopify | Sem pedidos reconhecidos: indisponível; sem projeção |
| ad_spend | Soma de `meta_spend` e `google_ads_spend` disponíveis | Origem informa somente fontes efetivamente presentes |
| roas | Meta: `meta_attributed_revenue / meta_spend`; Google: `google_ads_conversion_value / google_ads_spend` | Só uma fonte disponível; receita presente em todas as linhas de investimento; investimento positivo; fontes não são misturadas; sem projeção |
| conversions | `meta_purchases` | UI explicita “Compras atribuídas (Meta Ads)”; não mistura conversões Google de outra definição |
| followers | Último `instagram_followers` disponível no intervalo | Snapshot absoluto; sem extrapolação |
| reach | `instagram_reach` | Somente período de um dia; alcance único de vários dias não é somado |
| impressions | Soma de `instagram_impressions` | Depende dos snapshots persistidos |
| engagement | Soma de `instagram_interactions` | Contagem de interações, não taxa percentual |

Datas observadas são limitadas a hoje em America/Sao_Paulo. FBITS aplica limites de dia nesse fuso. Dados ausentes/erros de leitura retornam `actual: null`, motivo e status indisponível; não são convertidos em zero. A leitura é paginada até uma página vazia, inclusive quando a resposta traz menos linhas que o limite solicitado. O resolver rejeita leitura que atinja 20.000 linhas, evitando agregar uma base truncada silenciosamente.

Regras centralizadas em `evaluate_goal`: dias inclusivos, progresso `actual/target*100`, tempo decorrido limitado a 0–100%, delta em pontos percentuais. Meta atingida a partir de 100%; no ritmo até 5 pp abaixo do tempo decorrido; atenção até 15 pp; abaixo do ritmo além disso. Período futuro recebe status próprio.

Projeção linear somente para revenue/orders/ad_spend/conversions/impressions/engagement, com ao menos 5% do período decorrido e cobertura suficiente. Dados diários precisam cobrir cada dia observado por cada campo participante. FBITS exige histórico concluído desde antes do início e marcador de consulta cobrindo a data observada. Não extrapola seguidores, ticket, alcance ou ROAS. Projeção não garante resultado futuro nem atualidade completa dos dados intradiários.

## 5. Permissões

Viewer lê e não recebe ações de cadastro/edição/exclusão. Backend bloqueia suas três mutações com 403. Client admin altera o tenant autorizado; agência segue o escopo existente. Administração de plataforma e aliases legados são preservados pelo helper existente. Tenant não autorizado retorna 403; `client_id` extra no payload retorna 422. PUT/DELETE filtram simultaneamente tenant e UUID; meta ausente retorna 404. Autor da criação vem da identidade autenticada.

## 6. Telas

Nova `/metas`, item na navegação, período compartilhado, cards com realizado/meta/progresso/faltam/ritmo/status/origem/projeção condicional e formulários de criação/edição/exclusão com confirmação. Unidades BRL, quantidade e múltiplo ROAS. Viewer somente leitura.

Dashboard recebe resumo aditivo com no máximo três metas, ordenadas pela data final e criação, e CTA “Ver todas as metas”. A página Dashboard não foi editada nesta feature. Estado do formulário é remontado por tenant no App; leituras descartam respostas atrasadas, validam tenant da resposta e ocultam dados anteriores imediatamente.

## 7. Testes e verificações executadas

- `PATH=/tmp/mugo-refresh-venv/bin:$PATH npm test`: **581 testes frontend / 84 arquivos; 1329 testes backend; passou**.
- `npm run lint`: passou, sem warnings ESLint.
- `npm run typecheck`: passou.
- `npm run build`: passou; aviso informativo de tempo de plugins Vite.
- `git diff --check`: passou.
- `git status --short` e `git diff`: inspecionados; alterações de rodadas anteriores preservadas.

Testes novos em `server/tests/test_goals.py` (23):

| Classe / testes reais | Comportamento |
| --- | --- |
| RuleTests: `test_elapsed_pace_and_projection`, `test_status_thresholds_and_achieved`, `test_future_missing_zero_and_non_additive_have_no_projection`, `test_very_early_period_has_no_projection`, `test_backend_input_validation` | Matemática, status, futuro, cobertura insuficiente, divisões e payload |
| ActualTests: `test_fbits_revenue_orders_ticket_follow_existing_persisted_rule`, `test_shopify_revenue_orders_ticket`, `test_social_and_ads_persisted_with_correct_period`, `test_missing_provider_data_and_zero_ticket_are_unavailable`, `test_commerce_reporting_reuses_existing_fbits_precedence`, `test_persisted_read_failure_marks_goal_unavailable` | Fontes, período, isolamento defensivo, regra comercial existente e falha de leitura |
| AuthorizationTests: `test_create_edit_delete_and_scoped_filters`, `test_viewer_only_reads`, `test_cross_tenant_forbidden_and_payload_cannot_override`, `test_agency_admin_uses_existing_scope_authorization` | CRUD, autor, filtros, 403 e 422 com helpers de autorização reais e armazenamento simulado |
| MigrationTests: `test_additive_table_is_tenant_scoped_and_browser_read_only` | Contrato textual SQL de tenant/RLS/grants; não executa PostgreSQL |
| ConditionalMetricTests: `test_roas_single_source_only_and_zero_safe`, `test_multi_day_reach_is_not_summed`, `test_disconnected_provider_is_unavailable`, `test_persisted_resolution_never_sends_external_http`, `test_partial_daily_coverage_disables_projection`, `test_each_paid_source_needs_coverage_for_projection`, `test_short_pages_are_read_until_empty_without_truncating_actual` | Condicionais de fontes, HTTP proibido e cobertura de projeção |

O helper dos testes de fontes também bloqueia `httpx.AsyncClient.send`; leituras de armazenamento são simuladas.

`src/pages/Goals.test.tsx` (7 testes reais): “viewer lê progresso, origem e projeção sem mutações”; “admin cria, edita e exclui somente via ações explícitas”; “dashboard mostra no máximo três metas e CTA”; “troca de tenant oculta metas anteriores e descarta resposta atrasada”; “erro de gravação mantém metas e formulário”; “dados ausentes ficam indisponíveis sem números fabricados”; “formulário do tenant anterior não grava após mudança da empresa ativa”.

`src/app/routes.test.ts`: `distinguishes goals from the existing Meta route` protege `/metas` contra colisão com `/meta`. O teste de navegação do App recebeu somente um stub do resumo, que possui testes próprios. O contrato de migrations foi atualizado para a 43ª migration e mantém as verificações de sequência anteriores.

## 8. Riscos / limites de confirmação

- Migration e políticas RLS não foram executadas em banco PostgreSQL nem Supabase remoto; testes SQL são estruturais. Aplicação e smoke de CRUD/RLS em ambiente homologado continuam necessários.
- Dados desatualizados ou parcialmente persistidos refletem o armazenamento existente; esta feature não corrige cobertura nem dispara sincronização. Não há SLA de atualização novo.
- FBITS usa cálculo derivado de pedidos, identificado na origem; não reproduz diretamente o KPI oficial do provider.
- Reach multi-dia e ROAS com múltiplas fontes são deliberadamente indisponíveis por falta de definição comparável persistida.
- Limite de 20.000 linhas pode impedir cálculo para bases grandes; aumentar escala exige revisão posterior.
- Não foi feita homologação visual em browser autenticado nem smoke real de produção. Funcionamento remoto: **NÃO CONFIRMADO NO CÓDIGO.**

## 9. Arquivos desta feature

Novos: `server/routes/goals.py`, `server/services/goals.py`, `server/tests/test_goals.py`, `src/app/goals.ts`, `src/hooks/useGoals.ts`, `src/components/GoalCard.tsx`, `src/components/GoalsSummary.tsx`, `src/pages/Goals.tsx`, `src/pages/Goals.test.tsx`, `src/styles/goals.css`, migration 000043 e este relatório.

Adições em existentes: `server/app.py`, `server/tests/test_migration_bootstrap_contract.py`, `src/App.tsx`, `src/App.onboardingNavigation.test.tsx`, `src/app/api.ts` (somente export dos helpers de transporte existentes), `src/app/routes.ts`, `src/app/routes.test.ts`, `src/components/shell/AppNavigation.tsx`, `src/design-review/ReviewApp.tsx` (registro de título exigido pelo tipo de rotas).

O diff acumulado do workspace contém ajustes anteriores em refresh/providers/Customer 360/autorização; eles não foram produzidos nesta feature. Em `api.ts`, o tipo opcional `sources` de refresh já era preexistente. Não houve commit, push, deploy ou alteração remota.

## 10. GO / NO-GO

**GO local para revisão/homologação da implementação. NO-GO produção sem revisão/aplicação manual da migration e smoke autenticado de CRUD, permissões e dados reais.** A tabela nova é obrigatória para persistir metas.
