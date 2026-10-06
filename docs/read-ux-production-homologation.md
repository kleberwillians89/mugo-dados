# P0 de leitura — pacote local e próxima homologação

## Evidência e limite de atribuição

A única leitura de produção com waterfall fornecido é GET /api/media,
request_id 45a4d2ab429a406b8c411b29a2a9d38f: 1654ms, seis round trips,
27 registros de 2026-07-09 até 2026-10-06. Fases informadas: auth 311ms,
membership 269ms, tenant 496ms, connection_validation 272ms,
connection_resolution 228ms, data_media 573ms, unclassified 3ms.
As fases são aninhadas: NÃO somar esses tempos.

Os vídeos foram descritos por texto; não há HAR nem waterfall medido por módulo.
NÃO CONFIRMADO NO CÓDIGO: tempo de login até dado útil em produção,
origem das chamadas Graph por aproximadamente 18 segundos e relação delas
com navegação. Não reutilizar a causa da Curavino para o 502 da Roove.
Origami 503, Roove Intelligence 502 e integrations 403 lento permanecem
incidentes sem causa atribuída por este pacote.

## Call sites Graph e correlação futura

As funções fetch_media_insights e fetch_media_comments, em ig_meta.py,
são chamadas por _run_sync_for_client_and_ig em instagram_sync.py. Caminhos existentes:

- Refresh manual: Dashboard → refreshProviderData(meta) → POST
  /api/clients/{client_id}/data-refresh/meta → provider_refresh →
  sync_instagram_for_client → sync_instagram_connection → execução do sync.
- Refresh legado/onboarding: refreshAll → POST /api/ig/refresh_all (ou alias /api/ig/sync) →
  api_refresh_all → ig_refresh.refresh_all → sync_instagram_for_client.
- Ativação/configuração: rotas Meta de ativação/assets → initial_sync →
  sync_instagram_connection.
- Agendamento: run_jobs ou POST /api/cron/ig_refresh_all →
  run_daily_instagram_refresh → sync_instagram_connection.

GET normal de media/comments/dashboard lê persistência. O histórico Instagram
paginado coleta metadados de mídia; não adicionamos insights/comments a esse fluxo.
Não foi encontrado outro chamador direto dessas duas funções no backend.
Reconciliation e backfill são origens instrumentáveis, não origem comprovada
para aquelas chamadas de produção.

Novo log, antes de cada invocação dessas funções:

```text
[meta][live_call] {"trigger_source":"manual_refresh","job_run_id":null,"request_id":"<request_id>","operation":"media_insights"}
```

O cron passa job_run_id quando disponível. ContextVar separa execuções concorrentes.
O contexto HTTP identifica refresh/backfill/reconciliation/onboarding por rota;
um eventual GET que chegasse ao Graph seria marcado navigation. Sem contexto,
a origem é unknown. Não são registrados media_id, tenant, token, URL com query,
texto, nome, e-mail, telefone ou payload. O log é por invocação da função;
paginação/fallback de métricas dentro dela pertence à mesma execução.

## Mudanças reais e dependências

| Área | Antes | Depois | Primeiro conteúdo / requests |
|---|---|---|---|
| Snapshot compartilhado | daily, sources, campaigns e products aguardados juntos | daily+sources publicados primeiro; campaigns/products independentes e solicitados pelo módulo | Cold: 4 consultas por página Supabase → 2 principais; +1 campaigns em Meta/Google ou +1 products em Ecommerce. Paginação pode acrescentar consultas. |
| Inteligência | Contexto, última análise e histórico aguardados juntos | Cada resposta publica seu estado; contexto ou análise existente libera a página | Continuam 3 GETs distintos; histórico não bloqueia o conteúdo principal. Não gera análise ao abrir. |
| Metas | Lista aguardava todos os actuals | GET include_actuals=false mostra definições; GET completo atualiza progresso | Cold: 1 GET bloqueante → 2 sequenciais, primeiro sem actuals. Warm: dados imediatos + 1 GET de revalidação. Mais um HTTP cold, menos dependências para a primeira renderização. |
| Ecommerce: conexão | Catálogo de conexões reabria loading ao remontar | Cache por tenant mostrado imediatamente; revalidação single-flight | GET /api/connections continua 1 por montagem/revalidação, independente do período; não usa catálogo administrativo /integrations. |
| FBITS | Summary aguardava orders; receita oficial podia consultar provider no GET | Summary publica antes; orders aguarda seção. Receita oficial vem de snapshot persistido | Cold: 2 GETs iniciais de FBITS → 1 summary crítico e 1 orders deferred. Demanda não repete summary. Refresh manual continua relendo após sync. |
| Shopify | Report e customers aguardados juntos | KPIs do read model independentes; detalhes têm cache e demandas separadas | 2 GETs de detalhes iniciais → 0 antes da demanda; +1 report na seção pedidos e +1 customers na seção clientes. |
| Google Ads | KPI aguardava campanhas/produtos do snapshot | Daily/sources primeiro, campanha independente, sem products nesse módulo | 4 → 2 consultas principais +1 campaigns. Fatos REMOVED e cálculos mantidos. |
| GA4 | Remount começava sem cache de report | Cache tenant+período e single-flight | Continua 1 GET de report, com dado anterior do mesmo scope durante revalidação. |
| Meta | Snapshot podia aguardar campaigns/products | KPIs independentes; products não é solicitado nesse módulo | Media/comments/monthly continuam no mecanismo de demanda existente; não reativamos catálogo administrativo. |

Esses números são grupos de requests encontrados no código, não totais medidos
por tela. Bootstrap, comparações de períodos e paginação têm requests próprios.
Não tratar janelas de comparação distintas como duplicação.

## Reuse Supabase dentro da request

Lista de memberships já lida no contexto pode responder à validação de uma
membership presente; ausência continua seguindo a verificação existente.
Conexão validada com tenant+connection_id é reutilizada na resolução, que mantém
checagem de plataforma/tipo. Auth e tenant continuam request-scoped.
Nenhum fato é compartilhado entre usuários ou requests.

Teste de unidade com contagem das consultas mockadas: quatro leituras de membership/conexão → duas.
Para o formato da leitura /api/media fornecida, previsão estática: seis RT → quatro
quando esses dois pares redundantes forem atendidos pelo reuse; não é medição
nova de produção. Legacy, cache frio de papel e fallback de schema podem ter
outros números. A instrumentação existente permanece para verificar isso.

## Cache, período e tenant

Reutilizados cache.ts (memória+sessionStorage, TTL) e readOnce.ts (single-flight).
Não foi adicionada biblioteca. Snapshot usa client_id+start+end; FBITS inclui
namespace/provider; GA4, metas e detalhes Shopify usam tenant+período;
conexões Ecommerce usam somente tenant; histórico de Inteligência usa tenant
no single-flight. Não se confundem períodos diferentes.

Voltar à tela mostra cache válido no primeiro render; revalidação não apaga
esse dado. Período não invalida conexões. Um período novo ainda precisa de sua
leitura; períodos visitados podem reutilizar cache válido. TTL expirado carrega.

Classificação: shell/rotas são globais; sessão/membership são do usuário;
conexões são do tenant; snapshot/report/metas são tenant+período.
Troca de tenant limpa ponteiros ativos, preserva caches segmentados e descarta
respostas atrasadas para scopes diferentes. Dados do tenant anterior não são
usados como placeholder do novo tenant. Logout continua limpando todos esses
caches, agora incluindo memória. Guards/backend/RLS não foram relaxados.

## FBITS oficial: limitação explícita

O GET anteriormente chamava fetch_official_kpis e podia fazer HTTP live em cache
frio. Agora lê somente metadata.official_kpi_snapshots da conexão FBITS existente,
por janela atual+anterior e connection_id. Sem schema novo. O refresh explícito
existente coleta e persiste números oficiais normalizados, preservando metadata
e retendo até 12 janelas. Nenhuma operação foi executada em produção.

Se a janela não tiver snapshot oficial persistido, o fallback existente de pedidos
persistidos permanece identificado por kpi_source/kpi_fallback_reason; não se
apresenta como receita oficial coletada nem retorna zero oficial inventado.
Um número oficial válido já visível é preservado se a revalidação só entregar
fallback. A próxima homologação deve conferir esse caso e a fonte exibida.

Os relatórios FBITS ainda agregam pedidos persistidos para métricas sem read model
próprio. Lazy loading reduz competição da lista no primeiro conteúdo; não se
alega substituição desse agregado por tabela nova nem redução comprovada do seu
volume em produção. Listas Shopify também conservam os limites existentes;
esta rodada adiou sua leitura, não introduziu paginação nova no backend.

## Instrumentação e preservação

Marcos do navegador com performance.now/marks: auth_start, auth_ready,
tenant_start, tenant_ready, snapshot_request_start, snapshot_ready,
first_useful_data e secondary_data_ready. Somente stage e elapsed_ms nos novos
logs de navegador. Marcos de snapshot são do contexto compartilhado; não são
uma medição completa de todos os endpoints por módulo. Correlacionar HAR seguro
com request_id e logs backend na homologação.

90 dias permanecem selecionados sob demanda, com leitura paginada do banco,
sem provider/backfill por selecionar período. Não reduzimos 90 para 30 dias.
As quatro funções de numeric grounding/repair foram comparadas por AST com HEAD:
inalteradas. Nenhuma alteração de prompt/modelo/retry/validator.

## Próxima homologação (sem executar neste pacote)

Coletar: login → tenant → snapshot → primeiro dado útil; abrir cada módulo;
voltar ao módulo; período novo e período já visitado; tenant A → B → A;
seções abaixo da dobra antes/depois da demanda; origem de cada chamada Graph.
Usar tempos de navegador e request_ids, contagem de requests e RT por request.
Não enviar Authorization, cookies, URLs com tokens, payloads, PII ou secrets.

1–3 segundos e teto de 5 segundos NÃO estão comprovados. Este pacote prepara
nova homologação; não certifica orçamento de performance de produção.

## Arquivos e staging futuro (NÃO executado)

41 arquivos pertencem somente a este pacote. A lista literal abaixo exclui os oito diffs paralelos e os demais untracked.

```sh
git add -- \
  docs/read-ux-production-homologation.md \
  server/app.py \
  server/routes/goals.py \
  server/services/connection_resolver.py \
  server/services/cron_jobs.py \
  server/services/fbits_official_kpis.py \
  server/services/fbits_reporting.py \
  server/services/goals.py \
  server/services/ig_meta.py \
  server/services/ig_supabase.py \
  server/services/meta_live_trace.py \
  server/services/provider_refresh.py \
  server/services/request_performance.py \
  server/services/tenant.py \
  server/tests/test_manual_refresh_pipeline.py \
  server/tests/test_provider_refresh.py \
  server/tests/test_read_ux_regressions.py \
  server/tests/test_request_performance.py \
  src/App.tsx \
  src/app/DashboardDataContext.test.tsx \
  src/app/DashboardDataContext.tsx \
  src/app/activeClient.test.ts \
  src/app/activeClient.ts \
  src/app/goals.ts \
  src/app/readPerformance.test.ts \
  src/app/readPerformance.ts \
  src/components/dashboard/FbitsExecutiveDashboard.tsx \
  src/hooks/dashboard/useActiveEcommerceProvider.test.tsx \
  src/hooks/dashboard/useActiveEcommerceProvider.ts \
  src/hooks/dashboard/useCampaignsRanking.ts \
  src/hooks/dashboard/useDashboardFbits.ts \
  src/hooks/dashboard/useDashboardGa4.ts \
  src/hooks/useFirstUsefulData.ts \
  src/hooks/useGoals.ts \
  src/pages/Ecommerce.test.tsx \
  src/pages/Ecommerce.tsx \
  src/pages/Intelligence.test.tsx \
  src/pages/Intelligence.tsx \
  src/pages/Login.tsx \
  src/pages/Shopify.test.tsx \
  src/pages/Shopify.tsx
```

Mensagem sugerida: `fix: render persisted reads progressively and trace Meta live calls`.

Paralelos preservados byte a byte e fora do index:

- `.gitignore`
- `server/routes/google.py`
- `server/routes/meta_legacy.py`
- `server/services/invitations.py`
- `server/tests/test_meta_onboarding_authorization.py`
- `server/tests/test_platform_admin.py`
- `src/components/shell/AppNavigation.test.tsx`
- `src/design-review/ReviewApp.tsx`

## Validação local concluída

- Frontend completo: 640 testes, 93 arquivos, aprovados.
- Backend completo: 1473 testes aprovados.
- Lint, typecheck, build e git diff --check aprovados.
- Nove testes frontend novos e sete backend novos; fixtures/testes do refresh ajustados.
- Numeric grounding/repair: arquivo intelligence.py inteiro idêntico ao HEAD.
- Index vazio; oito diffs paralelos comparados byte a byte com baseline.
- Nenhum staging/commit/push/deploy/migration/sync/backfill remoto executado.

Regressões novas verificam KPI independente de secundário lento/erro, cache no
remount, demanda por módulo sem reler base, memória de tenant preservada e limpa
no logout, cache de conexão, abertura de Inteligência sem geração, demandas
Shopify em StrictMode e FBITS sem repetir resumo, marcos seguros, reuse com
scopes distintos, definições de metas sem actual/provider, origens Graph
concorrentes e GET FBITS oficial persistido/refresh explícito.

GO para revisão/commit do pacote local e nova homologação. A meta de latência
em produção continua não comprovada; incidentes de produção sem correlação
continuam abertos.
