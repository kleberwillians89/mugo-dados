# P0 — confiabilidade e freshness dos dados

Data: 19/10/2026, São Paulo. Base: `13c893608cca0fcd494fbb2ed839f4fd3ac70a04`. Checkout Desktop autorizado nesta conversa. Trabalho exclusivamente local; sem commit, push, deploy, sync/backfill remoto, credenciais, migration, schema ou RLS.

## A. Diagnóstico e matriz

Os tempos e clientes mencionados no pedido são evidência fornecida pelo solicitante, não logs remotos lidos nesta execução. Não acessamos registros reais de Curavino/Roove nem executamos providers para reproduzir o incidente. Diferentes fontes podem legitimamente ter horários diferentes; uniformizar o texto ou escolher o maior timestamp esconderia essa diferença.

| Módulo / indicador anterior | Componente / leitura | Persistência e relógio anterior | Semântica / inconsistência comprovada | Tratamento |
| --- | --- | --- | --- | --- |
| Meta / mídia paga “Dados atualizados” | `Dashboard.tsx`, `useDashboardSnapshot`, `/api/dashboard/paid`, `/api/dashboard` | `dashboard_source_snapshots.last_success_at`; fallback `meta_connections.last_synced_at/last_sync_at` | O SQL de projeção grava `now()` mesmo sem provar coleta completa; `mark_connection_sync_partial` também avançava os dois relógios Meta. Uma projeção/parcial pode parecer sucesso completo. | Runtime usa `DataFreshness(meta_ads)`, distinguindo job/status e cobertura. Projeção isolada não é prova de sync. |
| Instagram / perfil | `Dashboard.tsx`, `/api/dashboard` | `ig_profile_snapshots`, `meta_connections`, projeção | Snapshot diário é observação do perfil; não é data da publicação mais recente nem cobertura de mídia. | Fonte `instagram`, dataset de insights; relógio de operação separado de datas dos fatos. |
| Instagram / mídia, comentários e meses | `CommentsPanel.tsx`, `useDashboardMedia`, `useDashboardComments`, `useDashboardMonthlyContent`, `/api/media`, `/api/comments`, `/api/media/monthly` | `ig_media.timestamp`; `sectionUpdatedAt` e `monthlyUpdatedAt` de GET no navegador; fallback operacional | O hook mensal grava `new Date()` após GET. Isso era mostrado como “atualizado”. Publicação em 17/10 não prova sync em 17/10. | No runtime, rodapés usam sync confirmado da fonte; saúde distingue `instagram_content`, com publicação mais recente e cobertura desconhecida. GET não avança sucesso. |
| Google Ads | `GoogleAnalytics.tsx`, `useDashboardSnapshot` | `dashboard_source_snapshots.last_success_at`, `google_ads_daily_stats` | Projeção e sync possuem relógios diferentes. Disponibilidade de campanhas não certifica coleta completa. | `DataFreshness(google_ads)`, sucesso e cobertura por jobs/metadata explícita, sem usar horário do GET. |
| GA4 | `GoogleAnalytics.tsx`, `useDashboardGa4`, `/api/google/ga4/report` e endpoints channels/campaigns/events | `ga4_daily_stats.updated_at` máximo vira `meta.last_synced_at`; Dashboard usa projeção | Relógio de gravação de linhas pode avançar antes de todos os relatórios e da projeção concluírem. O job ainda terminava como success com `collection_complete=False`. | Runtime usa contrato novo; coleta incompleta marca job parcial, retorna `partial=True` e não é sucesso no cron/fachada. |
| Ecommerce FBITS / KPIs | `Ecommerce.tsx`, `FbitsExecutiveDashboard`, `/api/fbits/dashboard` | KPIs de `metadata.official_kpi_snapshots[chave_exata]`; cabeçalho usava `integration_connections.last_sync_at` dos pedidos | KPI oficial e pedidos têm persistências e cadências diferentes. Um sync de pedidos recente não atualiza automaticamente o snapshot oficial daquele período. | Fonte `fbits_official`, timestamp da entrada oficial validada; campo separado para pedidos; sem snapshot/linhas comprovadas não mostrar zeros como resultado confirmado. |
| FBITS / pedidos e analíticos | `useDashboardFbits`, `/api/fbits/orders` | `fbits_orders`, `fbits_order_daily_stats`, metadata `last_success_at`/`last_attempt_at` | Analítico pode existir com KPI oficial indisponível; ausência de linhas não prova zero vendas nem completude. | Fonte `fbits` separada; último pedido é dado, não sync. Cobertura continua desconhecida sem certificado. |
| Shopify | `Shopify.tsx`, `/api/shopify/report`, read model | `integration_connections.last_sync_at`, `technical.last_success_at`, projeção | Os relógios identificam etapas diferentes. Um GET também não prova nova importação. | `DataFreshness(shopify)`, evidência da operação persistida e cobertura separada. |
| Dashboard / operação hoje | `OperacaoReal.tsx`, `ChannelTodaySummary.tsx` | Linha diária Shopify / valores presentes do read model | “Ainda não atualizado hoje” é ausência da linha/valor de hoje; não significa desconexão, nem prova que não houve vendas. | Mantido como disponibilidade do recorte; resumo global deixa explícita a saúde da fonte. |
| Inteligência / cabeçalho e movimentos | `Intelligence.tsx`, `/api/intelligence/context`, `/api/intelligence/latest` | `snapshot.last_sync_at` é o máximo dos horários das fontes; análise tem `completed_at/created_at` próprios | A fonte mais recente escondia as mais antigas no rótulo geral. Geração de análise não é sync. | Runtime remete ao resumo por fonte e mantém geração da análise separada. Campos legados e regras de grounding/repair preservados. |
| Inteligência / FBITS leve | `commerce_context.resolve_commerce_context(..., include_details=False)` | Conexão e snapshot oficial existente em metadata | O ramo retornava `status=unavailable` incondicionalmente, mesmo havendo snapshot oficial válido daquele período. | Reutiliza entrada oficial validada na leitura de conexão já realizada; ausência retorna motivo seguro específico, sem scan de pedidos/provider. |
| Metas | `Goals.tsx`, `GoalsSummary.tsx`, `GoalCard.tsx`, `/api/clients/{id}/goals`, `services/goals.py` | Metas e realizações de dados persistidos por período | Não há relógio próprio de sincronização exibido. Progresso é derivado; `updated_at` da meta não é sync de provider. | Saúde global aparece também nesta rota; cálculo e permissões de metas preservados. |
| Clientes | `Customers.tsx`, `/api/customers` | `refreshedAt` local depois da leitura; clientes/pedidos persistidos | Texto existente é “Base consultada”, corretamente um GET, não “provider sincronizado”. | Mantido com essa semântica; saúde global separada. |
| Integrações | `Onboarding.tsx`, `/api/clients/{id}/integrations`, `/connections`, `/api/connections` | `integration_connections` e `meta_connections` | Builder Meta escolhe o operacional mais recente entre orgânico/pago; mapeava partial/skipped para sync_success. Badge confundia autorização inválida com permissão insuficiente. | Partial/no_data têm valores próprios; card usa contrato novo por fonte; autorização inválida pede reconexão; refresh de configuração diz “Consultando conexão”. Diagnóstico operacional é identificado separadamente. |
| Saúde / todas as rotas autenticadas | `DataHealthProvider`, `DataHealthSummary`, `DataFreshness` | `/api/clients/{id}/data-health?start&end` | Novo contrato comum de leitura; não recebe credenciais nem dispara trabalho de provider. | Uma leitura por cliente/período; atualização explícita de status e releitura após refresh. Nenhum polling. |
| Páginas legais | `LegalPages.tsx` | Data editorial fornecida à página | “Última atualização” do documento legal não se refere às integrações. | Não alterado. |

CONFIRMADO
- Arquivos: `commerce_context.py`, `fbits_official_kpis.py`, `fbits_reporting.py`, `ga4_sync.py`, `instagram_sync.py`, `connections_service.py`, `Dashboard.tsx`, `GoogleAnalytics.tsx`, `Ecommerce.tsx`, `useDashboardMonthlyContent.ts`.
- Símbolos reais: `resolve_commerce_context`, `read_persisted_official_kpis`, `build_fbits_summary`, `_sync_ga4_for_period`, `_mark_connection_success`, `_SYNC_STATUS_MAP`, `monthlyUpdatedAt`.
- Evidência: ramos e campos descritos na matriz foram lidos; testes novos reproduzem os erros de classificação e a leitura FBITS leve.
- Conclusão: existem inconsistências de semântica no código; foram corrigidos o caminho usado no app e os registros de parcial que promoviam sucesso falso.

SUSPEITA / evidência remota pendente
- Curavino: o ramo leve explica uma possibilidade concreta de `commerce_provider=fbits, commerce_status=unavailable`, mas não prova que o snapshot oficial existia no período do log. Motivos agora distinguíveis incluem snapshot ausente, inválido, fonte não conectada e erro de resolução/leitura. O caso real, suas datas e o conteúdo persistido precisam de leitura autorizada posterior.
- 4,2 segundos / seis round trips e GA4 com sete: não foram reproduzidos com conexão real. Reporting GA4 lê quatro conjuntos de fatos além da resolução/autorização. Tempo de rede, plano/índices e concorrência reais são NÃO CONFIRMADO NO CÓDIGO.
- Roove: os endpoints citados têm escopos/permissões e conteúdos diferentes. Não há evidência suficiente para substituir GET administrativo por GET de membro ou remover autorização. O ramo de apresentação extra do Dashboard que lista conexões tem `SHOW_PRESENTATION_EXTRAS=false`; os logs podem vir de outros caminhos/versões. Foi corrigida uma releitura comprovadamente redundante do hook GA4 ao remontar com cache válido do mesmo tenant/período.
- `GOOGLE_REAUTH_REQUIRED_INVALID_GRANT`: os registros fornecidos não foram consultados no ambiente remoto. O código de OAuth existente persiste `reauth_required`; saúde e UI agora o apresentam como reconexão necessária. Nenhuma tentativa automática de reconectar ou alteração do OAuth.

## Agendamentos automáticos

| Fonte / mecanismo local | Cadência no `render.yaml` | Evidência de execução em produção |
| --- | --- | --- |
| Meta token refresh, runner isolado | `15 */6 * * *` | NÃO CONFIRMADO NO CÓDIGO. Renovar/validar token não conta como sync de dados. |
| Instagram orgânico | `10 6,12,18,23 * * *`, 60 mídias; reconciliação semanal 250 sem thumbnails | NÃO CONFIRMADO NO CÓDIGO. Intervalo máximo nominal 7h. |
| Meta Ads | A cada hora; reconciliação diária de 30 dias; backfill worker a cada 5 minutos | NÃO CONFIRMADO NO CÓDIGO. Fila existente não foi executada. |
| GA4 | A cada 3h, janela de 3 dias; reconciliação diária de 30 dias | NÃO CONFIRMADO NO CÓDIGO. |
| Google Ads | A cada 3h, janela de 7 dias | NÃO CONFIRMADO NO CÓDIGO. |
| Shopify | Incremental a cada 30min; histórico diário e semanal; webhooks | NÃO CONFIRMADO NO CÓDIGO. Webhook recebido não garante entrega de todos os eventos. |
| FBITS / pedidos | A cada 30min; marcador persistido, overlap e cooldown | NÃO CONFIRMADO NO CÓDIGO. |
| FBITS / KPIs oficiais por período | Snapshot coletado somente no refresh explícito desse período | Não há cron declarado que atualize esses snapshots oficiais. O cron dos pedidos não os renova. |

`run_jobs.py` e `cron_jobs.py` despacham operações reais e iteram tenants; leases são persistidas em `cron_locks` e deduplicação Meta é local/temporária. Ao reiniciar, memória/cache/samplers locais desaparecem; checkpoints/leases têm persistência/expiração. “Running” sem lease vigente não é confirmado como em andamento. O pacote P0 limita trabalho pesado por processo e não é scheduler.

`render.yaml` declara plano starter e crons separados, enquanto o relato informa Free. Não há prova do plano/comando/serviços efetivamente aplicados. Não presumimos scheduler contínuo dentro do web, especialmente diante da suspensão Free informada pelo usuário. `schedule_verified` permanece false.

Solução incremental proposta, não executada: confirmar serviços, comandos, fuso e logs dos crons já declarados; medir última execução/erro por fonte e leases vencidas; homologar reconciliação idempotente após suspensão. Se os crons não estiverem provisionados, aprovar orçamento e ativação dos processos de jobs isolados existentes, ou execução dos mesmos comandos por agendador externo. Não adicionamos scheduler, keep-alive, fila, processo ou infraestrutura. Para KPIs oficiais FBITS automáticos, é necessário decidir períodos/custo antes de estender o job existente; atualmente isso não foi prometido nem implementado.

## B. Contrato e implementação

Endpoint somente GET, protegido por `require_client_read` antes das consultas. Resposta inclui `client_id`, período solicitado e oito fontes/datasets: Meta Ads, Instagram perfil, Instagram publicações, GA4, Google Ads, Shopify, FBITS pedidos e FBITS oficial.

- `last_attempt_at`: job.started_at ou metadata.last_attempt_at explícita; null quando não registrada. Não deriva de GET/configuração/login.
- `last_successful_sync_at`: término de job de sucesso não parcial, ou relógio de sucesso explícito da integração. Para Google Ads/Meta Ads, jobs são associados também à conta selecionada; relógios genéricos da conexão não substituem essa comprovação. Na maioria das fontes refere-se à operação da fonte, que pode abranger outra janela — o rótulo diz “da fonte”; não certifica o período selecionado. Para FBITS oficial é estritamente o snapshot do período e conexão exatos.
- `last_data_at`: última data de métrica persistida no recorte; para conteúdo Instagram é timestamp da publicação; para FBITS pedidos é timestamp do pedido. Essas semânticas são retornadas explicitamente. FBITS oficial é agregado, sem timestamp de última venda verificável: null.
- `coverage_end`: último dia coberto de modo contínuo a partir do início pedido, somente com job que declara coleta completa e projeção concluída. Datas com fatos, mínimo/máximo de campanha e projeção `now()` não certificam cobertura. O snapshot oficial validado certifica o agregado do intervalo, limitado ao dia em que foi coletado; não certifica datas futuras. Quando a evidência não existe, null.
- `sync_status`: success/partial/error/running/no_data/unknown com base persistida. Running requer lease de operação de dados vigente; token refresh não conta. “Unknown” inclui registro de execução antiga sem lease. No_data exige marcador explícito; disponibilidade desconhecida não vira zero.
- `error_code`: códigos seguros, sem erro bruto/token/payload; distingue falha, coleta incompleta, reconexão, ambiguidade, leitura e snapshots oficiais ausentes/inválidos.

Classificação: reconexão tem precedência; depois operação com lease, falha/parcial/leitura indisponível, atraso da operação, ausência/desconhecimento e cobertura insuficiente. Limiares nominais de atraso: Meta Ads 2h, Instagram 8h, GA4/Google Ads 6h, Shopify/FBITS pedidos 1h. Correspondem aos intervalos locais com margem, não a SLA remoto comprovado. FBITS oficial é manual, sem prazo automático inventado. Data antiga de fato não significa automaticamente atraso de sync; atrasos naturais/revisões dos providers e cobertura são apresentados separadamente. Sem evidência, não foi fabricado um D-1/D-2 como “completo”.

Leitura de saúde limitada a sete queries, com projeção de colunas e filtros tenant: até 50 conexões de cada origem, 100 jobs, 100 leases, 366 linhas diárias e um registro de data para pedidos/publicações. Não lê corpos de mídia, pedidos, comentários ou tokens; não busca histórico ilimitado. Os últimos 100 jobs podem não conter uma certificação antiga: nesse caso a cobertura fica desconhecida. Conexões múltiplas sem identidade única geram atenção, sem misturar relógios. O custo adicional de sete round trips pequenos precisa de homologação; essa leitura de status é separada da primeira leitura útil dos números.

`DataHealthProvider` mantém somente a resposta corrente no componente, com identidade cliente/período e descarte de respostas antigas. Compartilha a leitura com as páginas; nenhuma chamada por indicador e nenhum novo cache global. Refresh e endpoints legados POST com sufixo `/sync` sinalizam releitura do resultado persistido inclusive na falha; não usa o HTTP 200 para inventar sucesso. O botão de consultar status é GET. Ação de reconectar aparece apenas quando o app fornece permissão administrativa e leva à configuração existente, sem OAuth automático.

FBITS: o contexto leve reutiliza snapshot na consulta de conexão já feita; reporting reutiliza a conexão dentro da mesma operação, evitando nova leitura. Payload antigo continua com números legados por compatibilidade, mas agora explicita `data_available=false/data_status=unknown` quando não há oficial nem linhas; UI e contexto não promovem esses zeros a fatos. Oficial e pedidos possuem campos de sucesso separados.

Compatibilidade: endpoints e campos legados de projeção/reporting permanecem para consumidores existentes; não devem ser usados como contrato de freshness. No app autenticado, datelines e saúde usam o novo provider. Componentes renderizados isoladamente pelos harnesses legados mantêm apresentação anterior quando não há contexto; Integrações sem contexto diz que a situação não foi confirmada. O `snapshot.last_sync_at` agregado e os inputs de cobertura da política numérica da Inteligência foram preservados; o app não os usa para prometer freshness de todas as fontes. A única alteração em `intelligence.py` expõe `unavailable_reason`. Grounding e repair não foram alterados.

## C. Validação

- Testes backend/frontend, lint, typecheck, build e diff check executados; resultados finais abaixo.
- `test_data_health.py`: cenários de sync recente com fatos antigos e vice-versa; falha com sucesso anterior preservado; 200/parcial sem sucesso; ausência de cobertura; Google revogado; running após reinício/lease; outra conexão/propriedade; renovação de token; FBITS exato por período; snapshot inválido; consultas limitadas e filtro tenant; falha de leitura; autorização antes de ler; FBITS leve; parcial Instagram sem avançar sucesso; falha oficial sem sobrescrever snapshot; ausência sem afirmar zero; timestamp de publicação separado; status parcial/no_data canônico.
- `DataHealthContext.test.tsx`: troca de tenant/período e resposta atrasada, navegação sem sync/GET repetido, falha preservando evidência identificada, ação administrativa de reconexão e atualização após reler sucesso e cobertura persistidos.
- `useDashboardGa4.test.tsx::remontagem reutiliza relatório do mesmo tenant e período sem GET redundante`: cache existente por identidade, TTL 180s; refresh explícito continua relendo. Nenhuma autorização foi eliminada.
- `FbitsExecutiveDashboard.test.tsx::ausência sem cobertura comprovada não exibe zero como resultado`: não renderiza KPIs zero nem “Não houve vendas”. Asserções antigas FBITS e de reconexão foram atualizadas para a semântica correta, mantendo checagem dos números e permissões.
- Houve falhas intermediárias por localização incorreta de variável do timestamp, expectativas antigas de relógio/mensagem e uma alteração de campo legado que interferia em testes temporais. A variável foi corrigida; o campo legado foi restaurado integralmente. As regras numéricas não foram modificadas. Nenhuma falha remanescente foi mascarada como aprovada.

Memória: comparação offline em processos novos com `server/scripts/benchmark_memory.py`, 200 mídias/40 mil comentários e JSON simulado. Base P0: pico 43.663.360 bytes (~41,6 MiB), final igual. Atual: pico/final 41.598.976 bytes (~39,7 MiB). Ambos persistem os mesmos 40 mil comentários em lotes máximos de 200. Variação local de alocação não prova ganho adicional; o mecanismo P0 permanece.

Estresse da nova leitura: 200 operações simuladas, até 365 dias e 100 jobs por operação, sem rede/banco/mock que retenha todas as chamadas. RSS inicial 33.652.736 bytes, final 38.633.472; amostras após 50/100/150/200: 38.273.024 / 38.436.864 / 38.617.088 / 38.617.088. Não apareceu crescimento progressivo no trecho final desse ensaio; não é garantia de ausência de vazamento em produção nem substitui teste HTTP multiusuário no Render.

Verificação byte a byte contra `13c8936`: runners, cache, sampler/orçamento, streaming de imagem, locks de capacidade, processamento Ads e testes P0 intactos. No Instagram, o trecho de persistência e limpeza de lotes de comentários é idêntico; mudanças se limitam a avisos/classificação de parcial, sem alterar o limite ou fluxo de liberação.

Riscos/homologação: conferir relógios e fusos dos processos; plano e comando de start; job/lease após suspensão; conexão/propriedade selecionada; cobertura e dataset FBITS por período; invalid_grant sem retries automáticos; orçamento/memória e duração da leitura de saúde sob carga real. Verificar que períodos antigos não recebem cobertura atual por inferência. Validar os textos e a disposição do resumo em telas reais; QA visual completo em browser não foi realizado nesta etapa.

## D. Git e staging exclusivo proposto

HEAD permanece `13c893608cca0fcd494fbb2ed839f4fd3ac70a04`. Oito diffs paralelos comparados byte a byte com a referência anterior e a referência no início desta tarefa, preservados: `.gitignore`, `server/routes/google.py`, `server/routes/meta_legacy.py`, `server/services/invitations.py`, `server/tests/test_meta_onboarding_authorization.py`, `server/tests/test_platform_admin.py`, `src/components/shell/AppNavigation.test.tsx`, `src/design-review/ReviewApp.tsx`. Arquivos não rastreados anteriores não foram editados. Index vazio; nenhum git add, commit ou push nesta etapa.

Lista exclusiva proposta para revisão/staging posterior (34 arquivos, não executada):

- `docs/data-freshness-audit.md`
- `server/routes/integrations.py`
- `server/services/commerce_context.py`
- `server/services/connections_service.py`
- `server/services/cron_jobs.py`
- `server/services/data_health.py`
- `server/services/fbits_official_kpis.py`
- `server/services/fbits_reporting.py`
- `server/services/freshness.py`
- `server/services/ga4_sync.py`
- `server/services/instagram_sync.py`
- `server/services/intelligence.py`
- `server/tests/test_data_health.py`
- `server/tests/test_fbits_official_kpis.py`
- `server/tests/test_manual_refresh_pipeline.py`
- `src/App.tsx`
- `src/app/api.ts`
- `src/app/dataHealth.ts`
- `src/app/DataHealthContext.tsx`
- `src/app/DataHealthContext.test.tsx`
- `src/app/types.ts`
- `src/components/data/DataFreshness.tsx`
- `src/components/dashboard/FbitsExecutiveDashboard.tsx`
- `src/components/dashboard/FbitsExecutiveDashboard.test.tsx`
- `src/hooks/dashboard/useDashboardGa4.ts`
- `src/hooks/dashboard/useDashboardGa4.test.tsx`
- `src/pages/Dashboard.tsx`
- `src/pages/Ecommerce.tsx`
- `src/pages/Ecommerce.test.tsx`
- `src/pages/GoogleAnalytics.tsx`
- `src/pages/Intelligence.tsx`
- `src/pages/Onboarding.tsx`
- `src/pages/Onboarding.canonicalIntegrations.test.tsx`
- `src/pages/Shopify.tsx`

## E. Veredito

GO para revisão e commit posterior autorizado, após checks finais verdes. GO para homologação controlada em produção após revisão e autorização específica; esta etapa não realizou nenhuma operação remota. NO-GO para liberação aos clientes até confirmar a execução dos agendamentos, os snapshots/períodos dos clientes afetados, a propagação de reconexão e os limites de tempo/memória no Render. Atualização automática funcional e freshness real de Curavino/Roove permanecem não confirmadas remotamente.

Checks finais confirmados: `APP_ENV=production PATH=/tmp/mugo-memory-venv/bin:$PATH npm test` passou com **1.518 testes backend** e **658 testes frontend em 97 arquivos**. `npm run lint`, `npm run typecheck`, `npm run build`, compilação Python e `git diff --check` passaram. O build emitiu aviso de tempo gasto no plugin terser, sem falha. `git diff --cached --name-only` vazio. HEAD permanece na base P0. A lista exclusiva de 34 arquivos foi comparada com o working tree; os oito diffs paralelos foram novamente comparados byte a byte. Nenhum staging foi executado.

Nota operacional: resumos CLI de cron podem indicar que o runner terminou mesmo com falhas individuais em `connections_fail`; isso não deve ser usado sozinho como prova de sincronização. A homologação precisa examinar registros individuais, período, conta/propriedade, resultado e projeção. Não foi alterado o runner nem implementado monitor externo.

## F. Correção do bloqueador Meta Ads e nova revisão local

CONFIRMADO
- Schema existente: `supabase/migrations/20260417_000010_meta_ads_operational_stability.sql`, criação de `public.cron_job_runs`, coluna `ad_account_id text`; também presente no bootstrap `20260520_000014_client_data_minimum_schema.sql`. Foram apenas lidos, sem alteração ou execução.
- Causa: `compose_source.same_resource` consumia `job.ad_account_id`, mas a projeção de `cron_job_runs` em `client_data_health` omitia a coluna. Mocks anteriores entregavam o dicionário completo e não reproduziam a projeção real.
- Correção: inclusão de `ad_account_id` na projeção existente; associação exige também `client_id` igual ao da conexão. Para Meta Ads são necessários provider compatível, mesmo tenant, mesmo `connection_id` e conta identificada coincidente, normalizando somente o prefixo `act_`. Job sem conta ou conexão sem conta não certifica status/sucesso; nenhuma associação presumida por tenant. Múltiplas conexões ativas continuam gerando ambiguidade, sem mistura de relógios.
- Auditoria das outras projeções: `integration_connections` entrega id/tenant/provider/status/desconexão/metadata/último sync; metadata contém as identidades de propriedade GA4/cliente Google Ads e snapshots FBITS. `meta_connections` entrega identidade, conta, autorização/status e relógios Meta; desconexão Meta é determinada por status (o campo genérico `disconnected_at` é opcional e não é requerido nessa origem). Jobs entregam identidade/provider pelo nome, status, início/fim e payload dos certificados. Leases entregam tenant/nome/validade; métricas entregam tenant/dia e os cinco campos consumidos; pedidos/publicações entregam tenant e timestamp. Não foi encontrada outra coluna obrigatória omitida nessas sete projeções.
- Limites preservados: sete GETs, cada um filtrado por tenant e com limit explícito, rejeição adicional de linhas de outro tenant; endpoint autoriza antes de ler e limita período a 366 dias. Nenhum provider, sync ou escrita é chamado pela leitura de saúde. Sem cache global novo.

Testes novos em `server/tests/test_data_health.py`, classe `MetaAdsProjectionTests`:
- `test_selected_account_statuses_and_missing_identity`: sucesso/parcial/falha/skipped/running; rejeição de outra conta, conta ausente, outra conexão, outro tenant e outro provider; conexão sem conta não presume identidade.
- `test_multiple_accounts_and_running_are_isolated`: duas contas no mesmo tenant, leases por conexão, running com lease e skipped com no_data explícito.
- `test_projection_contract_and_selected_account_end_to_end`: contrato de colunas das sete fontes e mock que devolve apenas colunas selecionadas; job válido Meta Ads aparece no status/sucesso.
- `test_client_switch_does_not_reuse_previous_jobs`: segunda leitura de outro tenant não aceita o job anterior, mesmo com conexão de mesmo id no fixture.

Validação executada novamente após a correção: 27 testes específicos passaram; `APP_ENV=production PATH=/tmp/mugo-memory-venv/bin:$PATH npm test` passou com **1.522 backend** e **658 frontend em 97 arquivos**. `npm run lint`, `npm run typecheck`, `npm run build` e `git diff --check` passaram; somente aviso de tempo do Terser. Logs locais `/tmp/mugo-meta-specific.log`, `/tmp/mugo-meta-full-tests.log`, `/tmp/mugo-meta-lint.log`, `/tmp/mugo-meta-types.log`, `/tmp/mugo-meta-build.log`.

Revisão integral retomada dos 34 arquivos da seção D, incluindo conteúdo dos novos arquivos e diffs dos rastreados: alterações pertencem ao pacote de freshness; sem migrations/RLS/schema/OAuth ou código alheio. Nesta correção foram editados somente este relatório, `server/services/data_health.py` e `server/tests/test_data_health.py`, já incluídos na lista. **Lista final permanece exatamente os mesmos 34 caminhos da seção D, incluindo o relatório; nenhum arquivo novo foi necessário.**

Oito diffs paralelos idênticos byte a byte a `/tmp/mugo-existing.patch` e `/tmp/mugo-freshness-parallel.patch`. Runners, cache, sampler/orçamento, streaming, locks, Ads e testes centrais de memória idênticos ao HEAD P0. Branch main, HEAD `13c893608cca0fcd494fbb2ed839f4fd3ac70a04`, index vazio. Nenhum staging/commit/push/deploy, sync remoto ou alteração remota de dados.

Veredito atualizado: **GO técnico para commit após nova autorização específica**, limitado aos 34 arquivos. Validação real no Render, crons e dados dos clientes continua pendente; não representa resolução de incidente nem liberação aos clientes.
