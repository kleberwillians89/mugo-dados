# Auditoria de estabilidade — Mugô Dados

Data: 20/10/2026, São Paulo. Checkout `/Users/k/Desktop/mugo-dados`, autorizado nesta conversa. Base e HEAD preservados: `35e138b8ed1b67cba77606a4724c5e66458e6348`, branch `main`.

## Diagnóstico e limite da entrega

Escopo exclusivamente local: inspeção, correções, mocks, build, benchmark sintético e roteiro de homologação. Não consultamos Render, Meta, Google, Shopify, FBITS ou banco reais. Não lemos arquivos de credenciais. Nenhum commit, staging, push, deploy, sync ou backfill remoto. Não há evidência para declarar estabilidade definitiva em produção.

Inventário fechado desta rodada: **18 itens de risco, 11 tratados localmente e 7 abertos**. Dos 11 tratados, 10 são defeitos de confiabilidade/estado e um é alinhamento explícito de permissões com a nova missão (R10). Hipóteses remotas não foram contadas como bugs reproduzidos. P0 abertos: **R12, R13, R14**. P0 tratados localmente: R04 e R10, ainda sujeitos à homologação.

CONFIRMADO
- `provider_refresh.refresh_provider_data` agregava exceções de capacidade como erro 502 e consumia cooldown antes de detectar processo ocupado; `ads_sync.sync_ads_for_client_period` marcava a conexão como falha de provider nesse caso.
- `cron_jobs` selecionava conexões ativas sem conferir `clients.status`; `meta_backfill.process_next_slice` também não conferia o status da empresa antes do provider. Resumos de cron mantinham `ok=true` com `connections_fail>0`.
- `App.resolveTenantBootstrap` construía seletores a partir de memberships/colunas públicas sem status; `clients.list_clients_for_user` também não eliminava empresas inativas.
- `DataHealthProvider` iniciava reload para cada evento durante GET em voo. O transporte já compartilhava GETs idênticos: isso podia reaproveitar leitura anterior à conclusão do sync, não necessariamente produzir várias chamadas de rede. Agora há uma única releitura posterior quando houve invalidação durante a leitura.
- `Shopify.onRefreshData` verificava tenant no sucesso, mas não no catch/finally; também faltava a identidade do período na proteção da resposta.
- `_finish_job_run_reliably` e `_release_lock_reliably` usavam `wait_for(shield(task))`: timeout não encerrava a tarefa original. Dois testes reproduziram tarefas vivas após o helper retornar.
- `refreshProviderData` herdava timeout de leitura de 25s. Teste com relógio simulado reproduziu aborto antes de 201,68s, duração de uma requisição fornecida pelo usuário. Esse é um erro de contrato de espera do browser, **não a causa comprovada do HTTP 502 histórico do servidor**.

## Matriz de riscos

| ID | Prioridade | Evidência / causa | Tratamento / estado |
| --- | --- | --- | --- |
| R01 | P1 | Capacidade recusada em uma fonte Meta/Google entrava na classificação genérica 502 | Preserva `PROCESS_MEMORY_BUSY`/503; teste da corrida após preflight. Corrigido localmente |
| R02 | P1 | Fachada adquiria cooldown antes da admissão de memória | Preflight antes de qualquer lease/cooldown; guarda concreta continua autoritativa. Corrigido para processo já ocupado |
| R03 | P1 | Eventos durante GET podiam compartilhar evidência anterior ao término do sync | Coalescimento por tenant/período + uma releitura após conclusão, sem polling. Corrigido |
| R04 | P0 | Crons/backfill podiam operar empresa inativa | Consulta limitada de status, sem token; falha de leitura impede provider. Slice inativo é skipped, história preservada. Corrigido |
| R05 | P1 | Membership podia reintroduzir empresa inativa no seletor | Listagem autenticada filtra status; bootstrap usa essa API e remove seleção inválida. Corrigido |
| R06 | P1 | Catch/finally Shopify não conferiam escopo; período também podia mudar | Guarda tenant+período, limpeza de estado ao mudar escopo e mensagem de ocupado. Corrigido |
| R07 | P1 | Cleanup shielded sobrevivia ao timeout e podia sobrepor tentativas | Cancela e aguarda a tarefa antes de sair/repetir; espera pós-cancelamento também limitada. Corrigido |
| R08 | P1 | Timeout padrão 25s menor que refresh observado | Apenas refresh manual usa teto finito de 600s, sem retry; teste de 201,68s. Corrigido para esse contrato; teto precisa calibragem real |
| R09 | P1 | `ok=true` no cron com falha individual | `ok` exige todos os resultados bem-sucedidos; contadores/fontes preservados. Corrigido |
| R10 | P0 | Contrato anterior autorizava viewer em Metas e refresh de providers | Alinhado à missão: leitura mantida, CRUD Metas e POST agregado de refresh exigem papel administrativo; UI acompanha. Alinhamento local, não alegação de incidente de segurança anterior |
| R11 | P1 | Ads tratava recusa de admissão como falha de coleta/conexão | Job skipped com código de ocupado; não altera o resultado anterior da conexão; nenhum Graph iniciado. Corrigido |
| R12 | P0 | Exceção/flag original de `0caf…`/`61db…` não foi fornecida | Aberto, depende de logs históricos ou próxima ocorrência instrumentada em produção |
| R13 | P0 | Limite Render 512 MB; pico real sob carga não medido nesta missão | Aberto, depende de RSS/concorrência/ambiente reais; ensaio local não certifica margem |
| R14 | P0 | Status/registro real da Amalie não consultado nem alterado | Aberto; desativação real depende de aprovação e operador autorizado, sem exclusão |
| R15 | P1 | Saúde dos Dados observada em ~2,9–3,5s; demais leituras sem série de latência | Aberto, depende de medição real; sete queries limitadas continuam, sem promessa de ganho em segundos |
| R16 | P1 | Blueprint starter/crons versus ambiente Free relatado; locks/TTL sob suspensão não homologados | Aberto, depende de infraestrutura e logs. Orçamento é por processo; não é coordenação global entre serviços |
| R17 | P1 | Estado real das credenciais/expiração/providers não foi validado | Aberto, depende de acesso autorizado e homologação das conexões, nunca colar segredos em logs |
| R18 | P1 | Resultado Instagram `6bc3f3c21a0a458288cb6f97aece4b71` não acompanhado de logs | Aberto. Não consultamos histórico do Render; não inferimos sucesso/falha pelo Request ID |

## Mapa dos fluxos críticos

| Fluxo | HTTP / consultas / chamadas externas | Cache, corrida, erro e isolamento |
| --- | --- | --- |
| Login/auth | Supabase Auth; bootstrap lê platform_admins/memberships e `GET /api/clients` | Bearer validado no backend; auth/tenant/membership memoizados por requisição. Falha de bootstrap não vira acesso ao tenant salvo |
| Seleção/troca | API clients lê memberships sem expandir dados, checa platform admin, busca empresas em lotes <=100 para membros | Sem N+1 por empresa; só IDs autorizados voltam. Status inativo excluído; alias legado e seleção canônica preservados. Páginas têm key por tenant; estados dos providers são identificados por tenant/período |
| Dashboard | Browser lê dashboard_daily_metrics/source_snapshots e secundários campanha/produto persistidos via Supabase/RLS | Paginação estável e teto existente 200 mil registros, cache de período 15min e Promise em voo. Publicação é gated por scope; falha mantém último snapshot. Navegação não chama sync |
| Saúde dos Dados | GET data-health, autorização antes da leitura; sete queries em paralelo e limitadas (50/100/366/1) | Nenhum token/provider/write. Uma resposta por componente/escopo; eventos agregados em voo geram uma releitura necessária. Relógios de tentativa, sucesso, fatos e cobertura continuam distintos |
| Integrações | GET integrações/conexões; mutações administrativas nas rotas existentes | Cache de conexões/integrações; leitura não inicia refresh. OAuth não alterado. Reauth e parcial não são sucesso. Credenciais permanecem no backend |
| Atualização manual | POST data-refresh/provider, apenas admin; lease fachada + cooldown + lease concreta + orçamento de memória | Sequencial, recusa 503 preservada, sem retry automático. Read-model é relido após sucesso. HTTP parcial permanece falha agregada e dados anteriores continuam disponíveis |
| Atualização automática | run_jobs → cron_jobs por conexão; RPCs de lease e registros cron_job_runs | Filtra status ativo da empresa antes dos providers; um erro não bloqueia outras empresas. Resumo agora sinaliza falhas. Workers separados não compartilham contador RSS/admissão |
| Inteligência | GET context/latest/history persistidos; POST analyses/ask explícitos; provider IA somente na ação de geração | Cache/locks existentes por escopo; geração pesada usa admissão. Grounding, repair e política numérica intactos. Erro de fonte não é licença para fabricar número. Permissão existente de gerar análise por membro foi preservada; edição de contexto continua administrativa |
| Metas | GET goals com fase base e realizações; POST/PUT/DELETE exigem require_client_role e filtro tenant+id | Hooks descartam respostas antigas; viewer lê sem CRUD. Sem grant/policy de escrita para browser no schema existente. Valores indisponíveis não viram realizado zero |
| Clientes / Customer 360 | GET /api/customers e /{id}, resolve provider pela conexão; scans persistidos limitados a 20 mil e página <=100 | Sem live por cliente; chave opaca por tenant; truncamento sinalizado. Abort/generation guards na UI. Agregação em memória precisa de ensaio sob carga real (R13/R15), não foi reescrita |

Os papéis anteriores permitiam viewer em refresh e Metas de propósito, com testes explícitos. Esses testes foram atualizados para o novo requisito de ausência de escrita nessas ações; os cenários de refresh continuam exercitados com admin. Não houve afrouxamento de autorização/RLS, nem retirada dos testes de isolamento. Geração/consulta de análises segue contrato próprio já existente, sem alterar numeric grounding/repair. Caso o produto queira bloquear também geração/conversas para viewer, exige decisão explícita sobre esse contrato; não foi tratado como falha de autorização comprovada nesta rodada.

## Sincronizações por provider

- Instagram: admissão e lease em `sync_instagram_connection`, comentários persistidos progressivamente em lotes <=200; parcial preserva relógio de sucesso anterior. Ingestão não alterada. Perfil/publicação/cobertura continuam conceitos separados. Request ID histórico R18 permanece sem diagnóstico.
- Meta Ads: mantém conta/conexão/tenant, readback, projeção e job terminal. Refusal busy não marca provider quebrado. Cleanup de finish/release agora encerra a tarefa pendente no timeout. Falha de DB ainda pode impedir finalização; TTL e homologação são necessários, não garantia de escrita com banco indisponível.
- GA4: lease por propriedade, falha parcial não promovida a sucesso; cron consulta empresa ativa. Nenhuma alteração OAuth/queries provider.
- Google Ads: lease por conexão e job antes/depois da operação; cron consulta status da empresa. A fachada deixa passar recusa de memória como 503. Não alterados coleta, seleção de conta ou tokens.
- Shopify: admissão acontece antes do corpo de sync/job; preflight da fachada evita cooldown quando já ocupado. UI usa mensagem compreensível e preserva números. Catch/finally de tenant/período antigos não atualizam o escopo atual.
- FBITS: histórico/incremental e snapshot oficial por período preservados. Cron filtra empresa inativa. Falha de snapshot oficial continua sem substituir sucesso anterior; ausência não vira zero confirmado. Oficial só é atualizado em ação explícita; cron de pedidos não certifica KPI oficial.

A leitura de capacidade antes do cooldown é preventiva, não uma reserva: outra tarefa pode começar durante awaits de banco. A admissão concreta ainda impede concorrência pesada, mas nessa corrida o cooldown já adquirido pode durar até 60s. Não o liberamos sem prova de propriedade. Nenhuma fila, scheduler ou infraestrutura nova foi introduzida.

O log `lock_release_complete` significa fim do helper, não confirmação de sucesso da RPC. `lock_release_failed` e o TTL precisam ser examinados na homologação. Os dois escopos de lock do refresh Meta permanecem distintos; não removemos uma proteção para obter 200. Helpers agora drenam as tarefas com cancelamento cooperativo do IO; não prometemos interromper código que suprima cancelamento.

## Estado da Amalie e procedimento seguro

Evidência local de identidade: `src/app/activeClient.ts` mapeia UUID legado `9cd90217-ccba-4467-a095-eedc21fe6e86` para `amalie`. Isso **não confirma o ID/status atual no banco remoto**. Dependências pelo código/schema: clients, client_memberships/client_users, convites, meta_connections, integration_connections, cron_job_runs/cron_locks, jobs/slices de backfill, métricas/snapshots, mídia/comentários, pedidos/clientes Shopify/FBITS, análises/conversas e client_goals. Não enumeramos linhas reais nem volumes, pois não acessamos o banco.

Mecanismo existente: `clients.status` admite active/inactive/invitation_pending; `platform_admin.update_platform_company` aceita inactive. Não há necessidade de migration nem exclusão. Empresas inativas somem da listagem operacional e não entram nos oito runners periódicos; backfill reivindicado é encerrado sem provider. A tela administrativa pode continuar exibindo a empresa para suporte e história; não apagamos integrações, permissões ou fatos.

Procedimento **preparado, não executado**: após aprovação específica, operador administrativo identifica o registro e aliases corretos, confere dependências/jobs/leases em andamento, registra o estado anterior, define status inactive pelo fluxo administrativo existente, verifica seletor e próxima descoberta de cron sem iniciar sync manual, e confirma acesso administrativo ao histórico. Se um sync já estava em andamento no instante da desativação, a filtragem não o cancela retroativamente; coordenar a janela antes de desativar. Rollback apenas reativa o status sob nova decisão, sem recriar dados. Não usar exclusão permanente.

**Amalie não foi declarada removida da operação real.** O código para respeitar a desativação está pronto localmente; a alteração real é R14 e bloqueia liberação aos clientes.

## Testes e reproduções

Regressões principais desta rodada:
- `test_stability_release.py`: BusyAdmissionTests, CompanyLifecycleTests, CleanupLifetimeTests, CronAggregateTests e CompanyBatchingTests. Exercitam recusa sem cooldown, corrida 503, status inativo/missing/outro tenant, oito crons, backfill, falha de leitura sem provider, preservação histórica, cleanup sem tarefa órfã e agregação sem falso sucesso; 250 memberships usam três leituras de empresa, cada uma <=100.
- `test_ads_sync_resilience.py::BusyAdsOutcomeTests.test_capacity_refusal_is_skipped_without_marking_provider_failure`: teste falhou antes e passou após a correção; provider não iniciado, job skipped, conexão não marcada com erro, um release Ads.
- `DataHealthContext.test.tsx`: eventos simultâneos durante GET, releitura posterior, Roove → Ruah → Origami com respostas invertidas e disable/enable; cobertura não inventada.
- `Shopify.test.tsx`: erro antigo não contamina tenant novo nem prende loading; viewer mantém números sem sync. `syncOrchestrator.test.ts`: mensagem de memória ocupada, uma chamada sem retry.
- `api.ecommerceSync.test.ts::refresh manual aguarda operação de 201s sem abortar aos 25s nem repetir POST`: relógio simulado; falhou antes e passou após teto específico.
- `App.onboardingNavigation.test.tsx`: Amalie inativa não é reintroduzida por membership/seleção salva; viewer não recebe CRUD de Metas.
- `test_goals.py::AuthorizationTests.test_viewer_reads_but_cannot_create_edit_or_delete_even_own_tenant` e `test_provider_refresh.py::RefreshAuthorizationTests.test_viewer_cannot_start_any_provider_refresh`: leitura preservada e escritas recusadas antes do trabalho.

Cobertura dos 20 cenários pedidos (parte já existente, lida e executada):

| Cenário | Evidência de teste |
| --- | --- |
| Troca rápida / respostas antigas | DataHealthContext: Roove → Ruah → Origami; Shopify erro tardio; App troca validada |
| Meta sucesso + Instagram falha | test_ads_sync_resilience: `test_instagram_exception_reproduces_502_after_successful_ads_finalization` |
| Instagram sucesso + Ads falha | test_provider_refresh: `test_ads_failure_is_identified_after_organic_success` |
| Refresh parcial | test_data_health: `test_partial_http_success_never_becomes_successful_sync`; teste HTTP Instagram parcial |
| Shopify ocupado | BusyAdmissionTests; mensagem/teste sem retry no syncOrchestrator |
| Duplo clique | GoogleAnalytics.refresh: `clique duplo compartilha um sync e mantém gráficos montados`; runExclusiveSync |
| Atualizações simultâneas | test_provider_refresh: `test_two_requests_never_start_two_syncs`; test_memory_stability: `test_busy_job_releases_distributed_lock_and_cancellation_releases_capacity` |
| Falha durante / após persistência | test_ads_sync_resilience: provider/projection/terminal-job failure; test_data_health: snapshot FBITS preservado |
| Liberação / job correto | testes Ads de finalização e cleanup; BusyAdsOutcomeTests; backfill inactive |
| Sem dados / credencial expirada | test_provider_refresh: `test_no_data_is_valid_consultation_not_missing_sync`; test_data_health: `test_revoked_google_token_requires_reconnect` |
| Empresa inativa | CompanyLifecycleTests + seletor Amalie inativa |
| Viewer / isolamento | testes de auth Metas/refresh; test_data_health: autorização antes da leitura e isolamento de contas |
| Navegação sem live | test_memory_stability: `test_navigation_and_startup_during_simulated_sync`; testes de navegação DataHealth |
| Saúde sem repetições desnecessárias | DataHealthContext coalescimento, rerender sem GET adicional e releitura após evento |
| Dashboard mantém último válido | Dashboard.channelReport: falha preserva cards/freshness; GoogleAnalytics.refresh: falha não relê snapshot parcial; Ecommerce snapshot anterior |

Falhas intermediárias reais: (1) teste de segurança bloqueou seleção de `clients.status` pelo browser — solução foi usar API, sem mudar grants/teste de segurança; (2) expectativas antigas permitiam viewer sync/CRUD e cron ok com falha — atualizadas com testes explícitos de negação e com cenários admin preservados; (3) edição inicial da listagem batch deixou bloco antigo com indentação inválida — corrigido antes da validação final; (4) reproduções cleanup/timeout/busy falharam antes das respectivas correções. Não foram mascaradas como sucesso.

## Verificações finais executadas

- `APP_ENV=production PATH=/tmp/mugo-memory-venv/bin:$PATH npm test`: **1.539 testes backend e 666 frontend em 97 arquivos, todos aprovados**. Log final `/tmp/mugo-stability-final-tests.log`.
- `npm run lint`: aprovado (ESLint frontend/TypeScript; não alegamos lint Python inexistente).
- `npm run typecheck`: aprovado.
- `npm run build`: aprovado; aviso de depreciação do Node e/ou tempo no Terser durante rodadas locais, sem falha de build.
- `APP_ENV=production /tmp/mugo-memory-venv/bin/python -m compileall -q server`: aprovado.
- `git diff --check`: aprovado.
- Logs lint/type/build: `/tmp/mugo-stability-final-lint.log`, `/tmp/mugo-stability-final-types.log`, `/tmp/mugo-stability-final-build.log`.
- Os fixtures novos de empresa ativa apenas fornecem a consulta de status aos testes antigos dos providers; a filtragem real é exercitada separadamente por CompanyLifecycleTests, incluindo falha de leitura e todos os runners. Nenhuma asserção de isolamento, persistência ou segurança de colunas foi removida para obter aprovação.

## Performance e memória — evidência e limites

Benchmark offline, processos novos, mesmo script `server/scripts/benchmark_memory.py instagram`, 200 mídias/40 mil comentários sintéticos e JSON simulado, sem providers/banco:

| Ensaio | RSS inicial | Pico observado / final | Maior lote | Registros |
| --- | ---: | ---: | ---: | ---: |
| Instagram extraído do HEAD `35e138b`, `--baseline-dir /tmp/mugo-stability-baseline-services` | 42.139.648 B | 43.876.352 B (~41,8 MiB) | 200 | 40.000 |
| Atual local | 40.058.880 B | 41.893.888 B (~40,0 MiB) | 200 | 40.000 |

Logs `/tmp/mugo-stability-memory-baseline.log` e `/tmp/mugo-stability-memory.log`. A ingestão Instagram é byte a byte igual ao HEAD; a diferença de RSS entre processos é ruído/alocação e **não demonstra otimização de memória**. O ensaio confirma a preservação do limite de lote nesse fixture, não o pico da API completa ou a margem no Render.

Medição por contagem: 250 memberships agora obtêm nomes/status em **três queries projetadas de empresas**, cada uma <=100, em vez de uma expansão por membership. Sem medir rede real, não convertemos isso em ganho de segundos. A descoberta de cron acrescenta uma leitura limitada de status por até 100 empresas distintas e por invocação, custo necessário para não executar inativas. Não há cache global novo de dados de clientes.

Saúde dos Dados continua com sete queries limitadas; não foi criada fila, polling nem cache global. O coalescimento evita callbacks duplicados e garante releitura após invalidação, não promete reduzir toda contagem HTTP: o transporte já deduplicava GET em voo. A duração real de 2,9–3,5s permanece R15. O teto de 600s é provisório para refresh explícito; não aumenta timeout de leituras comuns nem garante que proxies/servidor sustentem toda operação. Recalibrar com duração por fonte e limite efetivo da infraestrutura.

Proteções anteriores preservadas: worker único nos runners, cache backend com limites, admissão atômica por processo, comentários em lote, limite de download de imagem e ausência de sync na navegação. Não alteramos imports/grounding/repair da Inteligência nem schema/RLS/OAuth. Operações de geração IA continuam compartilhando admissão pesada; leituras persistidas não a reservam. Customer 360 ainda agrega scans de até 20 mil registros em memória: precisa de carga real antes de qualquer promessa sobre 512 MB.

## Pendências de infraestrutura e credenciais

- Confirmar plano/comando/workers realmente aplicados no Render. `render.yaml` declara starter e cron services; o relato informa limite 512 MB/Free. Código não prova provisionamento.
- Confirmar crons/fusos, últimas execuções por fonte, suspensão/reinício, TTL e liberação real de leases. JSON `ok=false` agora expõe falhas; `run_jobs.main` ainda só usa exit code específico para provider-history/coverage. Não usar exit 0 do runner como certificado de sync.
- Recolher erro por fonte e localização instrumentada de `0caf737a87b84ac098785cd221fb6cfb` e `61db3a30100f4014af23c2149cf2ee90`, ou de uma ocorrência autorizada posterior. 90 round trips também ocorreram em HTTP 200; duração/quantidade não explicam sozinhas o 502.
- Obter logs do Instagram `6bc3f3c21a0a458288cb6f97aece4b71`. Não foram acessados nem inventados.
- Operador autorizado verifica conexões/contas/propriedades e validade de credenciais, sem copiar tokens para o relatório. Reauth é ação explícita de administrador; não houve tentativa automática.

## Plano verificável de homologação (preparado; não executado)

Nenhum passo de produção abaixo foi executado. Requer autorização específica de ambiente, janela e ações live. Primeiro revisar os diffs e aplicar o pacote em ambiente de homologação pelo fluxo aprovado. Registrar SHA completo, plano, workers, limite de RAM, cliente/período/role e Request IDs. Não misturar isso com o estado de produção histórico.

| Empresa | Leituras iniciais | Exercício após autorização explícita |
| --- | --- | --- |
| Roove | Login admin/viewer, Meta/Instagram persistidos, Saúde, Inteligência, Metas, Customer 360 se disponível | Reproduzir refresh Meta, verificar resultados separados Ads/Instagram e logs finais/leases; sem assumir causa histórica |
| Ruah | Mesmos módulos e somente integrações efetivamente conectadas | Troca rápida Roove → Ruah → Origami, respostas lentas/invertidas, período antigo sem cobertura fabricada |
| Origami | Mesmos módulos, permissões e dados persistidos | Viewer sem CRUD Metas/refresh; admin com operações explícitas e isolamento da conta selecionada |
| Curavino | Comércio/datasets disponíveis, snapshot oficial por período quando FBITS estiver conectado, GA4/Ads quando aplicável | Falha de provider/reauth sem perda do snapshot; não usar sync de pedidos como atualização do KPI oficial |

Para todas: (1) login e troca de tenant sem live; (2) selecionar período com dados e sem cobertura; (3) conferir fonte, tentativa, sucesso, fato e cobertura contra a evidência persistida; (4) erro de leitura mantém última evidência identificada; (5) viewer sem mutações de configuração/Metas/refresh e cross-tenant 403; (6) geração de Inteligência apenas por ação explícita, com política numérica intacta; (7) Metas indisponíveis não viram zero; (8) paginação/PII do Customer 360 sem logs de conteúdo.

Somente após autorizar live: uma operação pesada por vez; simular/provider mockado para falhas antes de usar credenciais reais. Durante Instagram, tentar Shopify uma vez e confirmar 503/ocupado, leitura intacta e nenhum retry automático; não insistir no 429. Testar clique duplo, falha durante/após persistência, cancelamento, job terminal e RPCs de release com chaves distintas. Verificar ambas as fontes mesmo quando a fachada retorna 502. Confirmar que operação recusada não altera status anterior da conexão Ads. Os testes de falha em produção devem usar mecanismo controlado aprovado, sem corromper provider/dados reais.

## Critérios objetivos de GO/NO-GO

GO para iniciar homologação controlada: revisão aprova todos os diffs/alterações de contrato; checks locais verdes; ambiente e janela autorizados; operador com acesso aos logs/RSS e capacidade de interromper ações live; nenhum dado remoto alterado sem autorização.

GO para clientes exige todos os P0 abertos encerrados com evidência e, para as quatro empresas:
- zero evidência de dados cruzados; resposta antiga não aparece após troca; leitura/navegação sem POST de provider;
- viewer não grava Metas nem dispara refresh/configuração; preservar explicitamente o contrato de análises por membro ou aprovar sua alteração separadamente;
- resultados por fonte coerentes, sem sucesso agregado falso, sem avanço de sucesso por GET/parcial e sem zero como disponibilidade desconhecida;
- jobs/leases conferidos após sucesso, falha, cancelamento e reinício; nenhuma segunda operação pesada no mesmo processo; nenhuma tarefa de cleanup local remanescente;
- Amalie realmente inativa e fora da próxima descoberta operacional, com história íntegra;
- medir dez navegações por empresa após aquecimento, com até três leitores simultâneos e uma operação pesada: primeiro dado útil p95 <=3s e leituras comuns p95 <5s; desvios exigem diagnóstico, não promessa;
- alvo conservador de homologação RSS pico <=400 MiB no processo de 512 MiB, sem OOM. Após aquecimento e cinco ciclos, comparar baseline estabilizado e final após idle: crescimento <=max(20 MiB,10%) e sem tendência crescente nas últimas três execuções. Se o critério falhar, investigar allocator/objetos/volumes; não declarar vazamento só pelo high-water mark;
- teste de sessão expirada/invalid_grant pede reconexão apropriada sem retry live automático;
- crons efetivos e recuperação pós-suspensão comprovados, não apenas declarados em YAML.

NO-GO imediato: OOM/reinício sem explicação, qualquer mistura de tenants/contas, provider iniciado por navegação/viewer, snapshot perdido, status de sucesso sem evidência, Amalie ainda operacional, tarefa/lock retido sem recuperação verificada, ou dados/credenciais/logs insuficientes para fechar os P0.

Rollback proposto: revisão/reversão somente dos diffs deste pacote pelo fluxo autorizado; não apagar dados, não reverter os oito diffs paralelos, não aplicar migrations. Alteração de status da Amalie tem aprovação e registro próprios. Esta missão não executou rollback, release ou operação de produção.

## Veredito executivo

**GO técnico para revisão e preparação de homologação controlada. NO-GO para clientes ou declaração de estabilidade definitiva.** São 18 itens auditados: 11 tratados localmente, sete ainda abertos. A causa histórica do 502 e o OOM não foram declarados resolvidos. R12/R13/R15/R16/R18 dependem de observabilidade/ambiente reais; R14 depende da desativação autorizada; R17 depende de acesso autorizado às conexões/credenciais e possivelmente reconexão pelo administrador. Nenhuma credencial é necessária para os testes locais executados.

Mudanças de contrato que o revisor precisa avaliar: viewer perde CRUD Metas e refresh de providers; cron `ok` agora reflete falhas individuais; backfill de empresa inativa encerra slice sem provider; leitura de empresa via API torna indisponibilidade explícita, sem reintroduzir tenant por membership. Essas mudanças são intencionais para esta missão, compatíveis com leitura de histórico e sem alteração de schema.

## Arquivos desta missão e Git

Lista exata de 36 arquivos modificados/novos, sem staging:

- `docs/stability-release-audit.md`
- `server/routes/goals.py`
- `server/routes/integrations.py`
- `server/services/ads_sync.py`
- `server/services/client_lifecycle.py`
- `server/services/clients.py`
- `server/services/cron_jobs.py`
- `server/services/memory_budget.py`
- `server/services/meta_backfill.py`
- `server/services/provider_refresh.py`
- `server/tests/cron_fixtures.py`
- `server/tests/test_ads_sync_resilience.py`
- `server/tests/test_cron_automation.py`
- `server/tests/test_fbits_automatic_sync.py`
- `server/tests/test_goals.py`
- `server/tests/test_meta_backfill.py`
- `server/tests/test_provider_refresh.py`
- `server/tests/test_shopify_reconciliation_cron.py`
- `server/tests/test_stability_release.py`
- `src/App.onboardingNavigation.test.tsx`
- `src/App.tsx`
- `src/app/DataHealthContext.test.tsx`
- `src/app/DataHealthContext.tsx`
- `src/app/api.ecommerceSync.test.ts`
- `src/app/api.ts`
- `src/app/syncOrchestrator.test.ts`
- `src/app/syncOrchestrator.ts`
- `src/pages/Dashboard.channelReport.test.tsx`
- `src/pages/Dashboard.tsx`
- `src/pages/Ecommerce.test.tsx`
- `src/pages/Ecommerce.tsx`
- `src/pages/GoogleAnalytics.refresh.test.tsx`
- `src/pages/GoogleAnalytics.test.tsx`
- `src/pages/GoogleAnalytics.tsx`
- `src/pages/Shopify.test.tsx`
- `src/pages/Shopify.tsx`

Oito diffs paralelos preservados byte a byte nas duas referências anteriores: `.gitignore`, `server/routes/google.py`, `server/routes/meta_legacy.py`, `server/services/invitations.py`, `server/tests/test_meta_onboarding_authorization.py`, `server/tests/test_platform_admin.py`, `src/components/shell/AppNavigation.test.tsx`, `src/design-review/ReviewApp.tsx`. Todos os arquivos não rastreados anteriores tiveram seus hashes preservados. Index vazio, HEAD/branch inalterados. Nenhum git add, commit ou push executado nesta missão.

Limitação adicional de validação: frontend foi exercitado por testes de componentes/hooks em jsdom e build; QA visual completo em navegador e medições de rede real não foram executados. O roteiro acima precisa validar textos, botões, loading e layouts nas telas reais antes da liberação.

## Revisão pré-release rigorosa — 20/10/2026

**Este parecer substitui o GO preliminar acima: NO-GO para commit e push dos 36 arquivos como release completo.** Não alterei código nesta revisão. Somente este relatório foi complementado. A suíte verde do checkout não elimina dependências em diffs excluídos nem cobre todas as combinações de cancelamento.

### Bloqueadores comprovados

**B1 — Timeout de cleanup escapa após cancelamento (P1).**

CONFIRMADO
- Arquivo/símbolo: `server/services/ads_sync.py:104`, `_release_lock_reliably`.
- Evidência: a linha 110 executa `wait_for(task, timeout=...)` dentro de `except asyncio.CancelledError`. Uma exceção desse await não passa pelo `except Exception` irmão das linhas 111–116. O `finally` encerra a tarefa, mas não absorve a exceção.
- Reprodução offline executada: substituir `release_sync_lock` por coroutine bloqueada em `asyncio.Event`; criar tarefa do helper; esperar entrada na RPC; cancelar o helper; usar timeout sintético de 0,01s. Resultado real: `release_result=TimeoutError`, `all_rpc_tasks_done=True`. Nenhuma RPC real.
- Impacto: o helper chamado no `finally` de `sync_ads_for_client_period` pode substituir o resultado/exceção anterior por TimeoutError. Na fachada sequencial, Exception é agregada como falha e pode gerar HTTP 502, mesmo com trabalho anterior concluído. **Isso não identifica a causa histórica de 0caf/61db.**
- Correção mínima proposta, não implementada: colocar também a espera pós-cancelamento sob o tratamento de falhas de release existente; registrar somente classe da exceção e manter a política explícita de cancelamento/TTL, sem deixar TimeoutError mascarar o resultado anterior. Preservar cancelamento/drain da tarefa no finally.
- Regressão necessária: cancelar durante release com RPC bloqueada, confirmar prazo finito, ausência de tarefa órfã e tratamento de falha consistente; testar também RPC que falha nesse ramo e cancelamento após persistência/job success. Não forçar HTTP 200 em requisição cancelada nem alterar job persistido.
- Lacuna: `CleanupLifetimeTests.test_release_timeout_leaves_no_background_rpc` cobre timeout normal, não cancelamento seguido de timeout. `test_finish_timeout_drains_previous_attempt_before_retry` continua válido; finish possui tratamento interno que release não possui.

**B2 — Contrato de viewer incompleto no pacote exato (P0 de release).**

CONFIRMADO
- Os guards em `server/routes/goals.py` e `server/routes/integrations.py` negam as novas mutações a viewer corretamente. Os guards frontend também estão coerentes.
- Porém `git diff -- server/routes/google.py server/routes/meta_legacy.py` mostra que os guards de `/api/google/ads/sync`, `/api/google/ga4/sync` e `/api/ig/refresh_all` pertencem aos **oito diffs paralelos excluídos**. `/api/ig/sync` delega ao último. Na base HEAD, esses caminhos usam resolução de tenant sem exigir papel administrativo.
- Reprodução HTTP offline executada: carregar `HEAD:server/routes/google.py` em módulo temporário, montar seu router em FastAPI, simular usuário viewer do próprio tenant e mockar `sync_google_ads`. Resultado: **HTTP 200, sync_calls=1**. Mesma chamada no módulo do checkout: **HTTP 403, sync_calls=0**. Sem provider ou banco reais. Não foi necessário copiar ou modificar os diffs paralelos.
- Consequência: publicar somente os 36 arquivos não entrega o contrato declarado de bloquear refresh para viewer em todos os endpoints. Esconder botões e bloquear apenas a fachada não impede POST direto nas rotas legadas.
- Correção mínima proposta, não implementada: aprovação separada dos hunks de autorização dessas rotas e dos testes correspondentes, ou publicação prévia de pacote independente que os contenha. Não mover/absorver hunks protegidos silenciosamente e não ampliar a lista de 36 nesta revisão.
- Regressão necessária no artefato publicável isolado: viewer próprio tenant e outro tenant recebe 403 em todas as rotas diretas e agregadas, sem provider/persistência; admin próprio tenant continua autorizado; leituras de dados/Metas/Saúde continuam disponíveis. Não interpretar 422 por corpo inválido como prova de autorização.

### Revisão individual dos 36 arquivos

Lista conferida contra o manifesto: **36 caminhos únicos, 32 rastreados modificados + quatro novos**. O próprio relatório está incluído. Cada diff rastreado foi lido; os quatro arquivos novos foram lidos integralmente. “Aprovado” abaixo significa ausência de bloqueador próprio encontrado no diff, não aprovação do release que depende de B1/B2. **34 aprovados nesse sentido e dois reprovados.**

| Arquivo | Parecer | Evidência / limite |
| --- | --- | --- |
| `docs/stability-release-audit.md` | Aprovado | Parecer atualizado com bloqueadores e limites; substitui GO anterior |
| `server/routes/goals.py` | Aprovado | Escrita exige admin; GET mantém read; update/delete filtram tenant+id |
| `server/routes/integrations.py` | Aprovado | Fachada exige role antes de trabalho; B2 impede afirmar cobertura de todas as rotas |
| `server/services/ads_sync.py` | **Reprovado** | B1; busy skipped preserva conexão, mas release cancelado pode mascarar resultado |
| `server/services/client_lifecycle.py` | Aprovado | Cron exige active exato, batches <=100, filtra IDs retornados; sem cache |
| `server/services/clients.py` | Aprovado | Membro só recebe empresas de memberships e status permitido; admin global usa autoridade existente |
| `server/services/cron_jobs.py` | Aprovado | Oito descobertas filtradas; resumo reflete falhas individuais |
| `server/services/memory_budget.py` | Aprovado | Preflight advisory; admissão concreta sem await entre check e incremento; libera contador |
| `server/services/meta_backfill.py` | Aprovado | Impede provider para inativa/consulta falha; atenção à retomada terminal descrita abaixo |
| `server/services/provider_refresh.py` | Aprovado | Busy mantém 503; sequencial; cooldown com corrida residual declarada; instrumentação intacta |
| `server/tests/cron_fixtures.py` | Aprovado | Fixture valida projeção/tabela/lote; não substitui testes reais de lifecycle |
| `server/tests/test_ads_sync_resilience.py` | Aprovado | Busy não chama Graph/não marca conexão falha; testes anteriores de 502 mantidos |
| `server/tests/test_cron_automation.py` | Aprovado | Só acrescenta fixture de empresa ativa aos cenários existentes |
| `server/tests/test_fbits_automatic_sync.py` | Aprovado | Fixture adicional; seleção e isolamento mantidos |
| `server/tests/test_goals.py` | Aprovado | Viewer GET 200, CRUD 403 próprio/outro tenant, nenhuma escrita |
| `server/tests/test_meta_backfill.py` | Aprovado | Lifecycle mockado para testes antigos; cenário inativo real em stability_release |
| `server/tests/test_provider_refresh.py` | Aprovado | Viewer nega quatro providers; cenários admin e cross-tenant mantidos; não cobre B2 |
| `server/tests/test_shopify_reconciliation_cron.py` | Aprovado | Fixture ativa e expectativa ok=false em falha; mantém cenários de reconciliação |
| `server/tests/test_stability_release.py` | **Reprovado** | Cobertura de cleanup insuficiente para B1; demais testes busy/lifecycle/batches válidos |
| `src/App.onboardingNavigation.test.tsx` | Aprovado | Membership/seleção salva não reintroduzem inativa; viewer sem canManage |
| `src/App.tsx` | Aprovado | Listagem autenticada, canonicalização, seleção inválida limpa; backend deve publicar primeiro |
| `src/app/DataHealthContext.test.tsx` | Aprovado | Coalescimento, trailing read, troca inversa e disable/enable |
| `src/app/DataHealthContext.tsx` | Aprovado | Sequence+key descartam resposta antiga; uma releitura por invalidação pendente; sem polling |
| `src/app/api.ecommerceSync.test.ts` | Aprovado | 201,68s simulados sem abortar nem repetir POST; não certifica proxy |
| `src/app/api.ts` | Aprovado | Timeout 600s restrito ao refresh explícito; sem retry |
| `src/app/syncOrchestrator.test.ts` | Aprovado | Busy com mensagem e uma chamada |
| `src/app/syncOrchestrator.ts` | Aprovado | Só tradução de PROCESS_MEMORY_BUSY; sem concorrência adicional |
| `src/pages/Dashboard.channelReport.test.tsx` | Aprovado | Viewer sem botão; falha/snapshot continuam testados como admin |
| `src/pages/Dashboard.tsx` | Aprovado | Guard handler+botão por canSync |
| `src/pages/Ecommerce.test.tsx` | Aprovado | Viewer read; cenários de falha/tenant preservados como admin |
| `src/pages/Ecommerce.tsx` | Aprovado | Guard handler+botão por canSync |
| `src/pages/GoogleAnalytics.refresh.test.tsx` | Aprovado | Exercita refresh admin, preserva cenários de falha e duplo clique |
| `src/pages/GoogleAnalytics.test.tsx` | Aprovado | Viewer sem ação de sync |
| `src/pages/GoogleAnalytics.tsx` | Aprovado | Guard callback+botão por canSync |
| `src/pages/Shopify.test.tsx` | Aprovado | Erro de tenant antigo não altera atual; viewer disabled sem chamada |
| `src/pages/Shopify.tsx` | Aprovado | Tenant+período conferidos no sucesso/catch/finally; estado limpo ao mudar scope |

### Demais achados e limites (não bloqueiam isoladamente o commit)

- **Concorrência/cooldown:** recusa prévia não consome cooldown; corrida durante await ainda pode consumi-lo por até 60s. Guarda concreta impede segunda operação pesada no mesmo processo; não há coordenação global por RSS entre web/crons. Leituras não adquirem essa capacidade. Não foi aumentada concorrência.
- **Memória/timeout:** não encontrei materialização ou cache global novo de dados sensíveis nesses diffs. O benchmark anterior não foi reexecutado nem prova margem no Render. Timeout browser de 600s não certifica proxy nem cobre necessariamente soma de todas as fontes; homologar tempos e cancelamento reais.
- **Saúde dos Dados:** `client_data_health` mantém sete leituras limitadas, filtro tenant no banco e no retorno, sem provider/write; projeção cron inclui ad_account_id; conexão+conta permanecem exigidas. Testes de conta diferente, identidade ausente, parcial, skipped, running e troca de cliente passaram. Frontend coalesce eventos e relê após GET antigo. Não foi alterado backend de Saúde nesta revisão/pacote.
- **Empresas inativas:** remover seletor e oito descobertas de cron não equivale a revogar acesso por ID. `tenant.resolve_client_id` não consulta status; admin ainda pode disparar refresh direto com ID conhecido. `shopify_webhook`/`process_shopify_webhook_event` também não conferem clients.status e podem persistir/projetar evento de loja conectada inativa. Fluxos anteriores, não regressões introduzidas. Antes da desativação real, definir explicitamente se “inativa” significa também suspender webhooks/mutações diretas. **Não certificar suspensão integral apenas com este pacote.**
- **Backfill/reversão:** novo skipped CLIENT_INACTIVE é terminal. `_update_job` conta skipped como concluído e pode marcar parent success sem coleta dessas slices; o summary distingue slices_skipped e não certifica cobertura por si. Falha transitória de status vira slice error terminal. Reativar clients.status não retoma esses checkpoints automaticamente. Teste atual mocka `_update_job`; acrescentar teste de integração local do agregado/retomada antes de prometer rollback operacional completo. Sem autorização, não reabrir slices.
- **Volumes:** listagem global de empresas e leitura inicial de memberships continuam sem paginação explícita; batches limitam só lookup de empresas para membros. Risco de truncamento pelo teto PostgREST é preexistente, sem evidência de incidência no volume real. Não alegar paginação ilimitada resolvida.
- **Cron:** ok=false não muda exit code do runner para esses comandos; monitorar JSON/cron_job_runs, não apenas exit 0. Infraestrutura aplicada, credenciais e consumo real permanecem não confirmados remotamente.
- **Viewer:** análises/conversas conservam contrato próprio anterior. Esta revisão não o amplia para “nenhuma escrita em qualquer endpoint”. OAuth/RLS/grounding/repair não modificados pelo pacote.

### Dependências de publicação e migrations

Nenhuma migration nova/modificada está nos 36 arquivos; nenhuma foi aplicada. Dependências existentes a conferir no ambiente autorizado: `clients.status`/trade_name e platform_admins (`20260801_000020_platform_admin_companies.sql`), client_goals e sua política select-only (`20261007_000043_client_goals.sql`, cujo comentário local informa NÃO APLICADA), tabelas/RPCs de leases/jobs/backfill e read models usados pela base. **Estado remoto das migrations: NÃO CONFIRMADO NO CÓDIGO.** Não aplicar migration duplicada pela simples existência de arquivo local.

Sequência proposta somente após B1/B2 resolvidos e nova aprovação: revisar pacote publicável isolado; confirmar schema já existente por operador autorizado; publicar backend e todos os serviços cron com o novo módulo client_lifecycle; verificar `/api/clients` para platform_admin/agency_admin/membro; só então publicar frontend. Frontend novo depende da nova listagem backend para todos os papéis. Confirmar Python 3.13, worker único e plano/limites efetivos; Render YAML não prova provisionamento. Nenhuma dependência de biblioteca nova, alteração de OAuth ou RLS é necessária para os diffs atuais.

### Amalie: procedimento e reversão, não executados

1. Operador autorizado deve identificar registro **exato** por ID, razão/nome fantasia e aliases, confrontando `amalie` e UUID legado documentado. Se houver dois registros ou dependências divididas, interromper; não escolher só pelo nome. Identidade/status reais continuam NÃO CONFIRMADOS; nenhum registro remoto foi consultado nesta revisão.
2. Inventariar dependências por ID confirmado (listas acima), conexões/webhooks, jobs/slices/leases ativos e contagens históricas. Salvar estado anterior do status e checkpoints necessários em registro restrito; não copiar payloads/tokens/PII para este relatório.
3. Definir política dos webhooks e refresh direto antes da janela; garantir ausência de jobs em voo. Não cancelar jobs nem remover conexão como atalho. O filtro novo não cancela execução já admitida.
4. Sob autorização específica, usar **PATCH `/api/platform/companies/{client_id}` com somente status inactive**, mecanismo real que chama `update_platform_company` e grava platform_audit_events. Não executar DELETE, OAuth, sync ou SQL destrutivo.
5. Conferir retorno e leitura de status, seletor, descoberta operacional seguinte e integridade das contagens/snapshots; apenas observar agendamento, sem disparar backfill/refresh manual. Conferir também sessões já abertas e política definida no passo 3.
6. Reversão sob aprovação: restaurar **status original registrado**, que pode ser invitation_pending, não presumir active. Conferir seletor/autorizações sem iniciar provider. Comparar checkpoints: slices skipped/error pelo lifecycle exigem plano autorizado próprio de retomada. Status isolado não restaura processamento desses checkpoints.

Rollback do código: reverter somente o futuro commit deste pacote pelo fluxo aprovado, preservando base 35e138b, dados e oito diffs paralelos. Coordenar rollback frontend antes de backend para evitar frontend novo dependente de API antiga; manter operações de escrita suspensas se backend antigo voltar a permitir viewer. Não reverter migrations/grants, apagar fatos ou resetar cron_job_runs. Rollback de código, de política de acesso e de status da Amalie são decisões separadas.

### Validações repetidas nesta revisão

- `APP_ENV=production PATH=/tmp/mugo-memory-venv/bin:$PATH npm test`: **666 frontend / 97 arquivos e 1.539 backend, aprovados**; `/tmp/mugo-prerelease-tests.log`.
- `npm run lint`, `npm run typecheck`, `npm run build`: exit 0; logs `/tmp/mugo-prerelease-{lint,typecheck,build}.log`. Build emitiu aviso de tempo do plugin Terser, sem falha.
- `APP_ENV=production /tmp/mugo-memory-venv/bin/python -m compileall -q server` e `git diff --check`: exit 0.
- Dois ensaios adicionais offline demonstraram B1/B2 conforme resultados acima. São reproduções de defeitos, **não testes de regressão já corrigidos**. Não acrescentei testes/correções ao pacote nesta revisão.
- A suíte completa foi executada no checkout compartilhado, incluindo diffs paralelos. O ensaio HTTP carregando a rota da base demonstrou por que ela não certifica o artefato restrito aos 36 arquivos. Após resolver B2, repetir a suíte em árvore isolada contendo só os commits aprovados.
- Instrumentação `35e138b`: AST de **todos os prints** em provider_refresh e ads_sync igual à base; request_id e classificação/origem de falha preservados. Documento `docs/meta-refresh-502-audit.md` sem diff; testes de finalização/HTTP da instrumentação continuam presentes e passaram. Adaptação de fixture para require_client_role e novo teste busy não removem esses cenários. Nenhum novo log foi introduzido nesta revisão.

### Checklist de homologação e parecer final

- [ ] Corrigir B1 minimamente e cobrir cancelamento+timeout/erro de release, sem falsear sucesso.
- [ ] Resolver B2 por autorização/publicação separada; provar viewer 403 em todas as rotas de sync diretas e agregadas em árvore isolada.
- [ ] Reexecutar checks nessa árvore e revisar manifesto final antes de qualquer staging.
- [ ] Confirmar migrations/deploy order/worker/plano/limites reais; publicar somente sob nova autorização.
- [ ] Executar roteiro das quatro empresas acima: leituras, troca rápida, períodos, contas, viewer/admin e snapshots após falha.
- [ ] Homologar timeout, cancelamento, cooldown, cleanup, jobs terminais e locks/TTL; correlacionar fontes e Request IDs do 502 sem presumir causa histórica.
- [ ] Medir RSS e latências sob carga no Render conforme critérios acima, sem declarar OOM resolvido por testes locais.
- [ ] Confirmar registro/dependências/política de suspensão da Amalie e reversão dos checkpoints antes de qualquer desativação real.

Git conferido: HEAD `35e138b8ed1b67cba77606a4724c5e66458e6348`; index vazio. Os oito diffs foram comparados **byte a byte** com `/tmp/mugo-existing.patch` e `/tmp/mugo-freshness-parallel.patch`: idênticos. Todos os arquivos não rastreados anteriores conferidos por SHA256 contra `/tmp/mugo-stability-baseline.json`: preservados. Manifesto permanece exatamente 36; nenhum caminho foi acrescentado ao pacote. Nenhum staging, commit, push, deploy, migration ou sincronização real.

**NO-GO para commit e push.** B1 exige correção e regressão; B2 exige resolver dependência de autorização/escopo. Testes locais verdes não revogam esses bloqueadores. Homologação real continua pendente após nova revisão.

## Correção dos bloqueadores B1/B2 — integração isolada (20/10/2026)

Este adendo registra a rodada posterior à revisão acima. **B1 foi corrigido no checkout; B2 foi corrigido e validado em árvore isolada. Não aplicar GO ao checkout original ou à antiga lista de 36.** Nenhum commit, staging, push, deploy, migration ou chamada real de provider/banco foi executado.

### B1 — correção mínima e contrato

`ads_sync._release_lock_reliably` agora retorna confirmação booleana da RPC. As esperas normal e pós-cancelamento ficam sob o mesmo tratamento de falha; timeout/erro registra `lock_release_failed` com classe da exceção, retorna false e encerra a tarefa pendente. Cancelamento recebido pelo helper é guardado e **relançado após o cleanup**, inclusive quando a RPC conclui ou falha: não vira sucesso nem TimeoutError substituto. Exceções que não são Exception não são absorvidas genericamente.

No finally de `sync_ads_for_client_period`, o evento `lock_release_complete` conserva Request ID, tenant, conexão, chave e duração, acrescentando `released=true/false`. Complete significa helper concluído; **released=false significa liberação NÃO CONFIRMADA**, não prova de que o banco não executou a RPC. TTL continua como recuperação existente; não há retry pesado novo. Em cancelamento propagado o fluxo não imprime confirmação de liberação.

Persistência, job terminal e contrato HTTP não foram reescritos: erro original de provider continua erro; job já persistido com sucesso não é convertido em falha de coleta por erro de cleanup. HTTP 200 nesse último caso já era o comportamento do helper para erro normal de RPC; a regressão HTTP confirma esse contrato, sem forçar 200 nem declarar cleanup bem-sucedido. A falha de release é registrada separadamente. Cancelamento continua CancelledError. Não há prova nova da causa do 502 histórico.

Seis regressões novas em `server/tests/test_ads_sync_resilience.py`:
- `ReleaseFailureRegressionTests.test_cancelled_release_timeout_preserves_cancellation_and_drains_rpc`;
- `test_original_provider_error_survives_release_error`;
- `test_successful_release_is_confirmed`;
- `test_successful_persistence_is_not_rewritten_when_release_fails`;
- `test_release_failure_returns_false_instead_of_confirmation`;
- `ManualRefreshHttpFinalizationTests.test_ads_release_failure_keeps_persisted_success_and_reports_unconfirmed_lock`.

Os cinco primeiros foram executados antes da correção: três falhas e um erro, incluindo TimeoutError em vez de CancelledError. Depois, todos passaram. A regressão HTTP adicional confirma persistência de uma linha, job success, HTTP 200 e released=false quando apenas o release Ads falha. Testes existentes continuam garantindo que parcial Instagram e falha de finalização não sejam promovidos a HTTP 200.

### B2 — auditoria e integração seletiva

Área isolada: `/tmp/mugo-stability-publish`, extraída do HEAD esperado e sobreposta **somente** com os arquivos do pacote e hunks explícitos das duas rotas. Não é um worktree com index próprio; nenhum arquivo paralelo original foi escrito. Dependências Node reutilizadas por symlink local, sem instalar biblioteca nova. Arquivos de ambiente/credenciais foram excluídos da extração.

Hunks funcionais de autorização incluídos nessa árvore:
1. `server/routes/google.py`: importar require_client_role; Google Ads sync exige role antes do sync; GA4 sync exige role **antes de resolver contexto da conexão**, preservando 403 mesmo sem propriedade configurada. A ordem original do diff paralelo fazia essa resolução primeiro.
2. `server/routes/meta_legacy.py`: `api_refresh_all` exige role; `/api/ig/sync` continua delegando a ele, sem desativação da rota.
3. No mesmo arquivo Meta, a auditoria ampliada comprovou que `api_instagram_debug_identity` (GET) chama `discover_instagram_identity_for_connection` com `persist_if_unambiguous=True` por padrão. O helper pode escrever meta_connections e clients (`instagram_sync.py:235–243`). **Essa operação de descoberta/configuração também exige role na árvore isolada.** Dados/status somente leitura continuam acessíveis ao viewer. Não houve alteração do protocolo OAuth.

Demais caminhos inspecionados:
- Google: dois POSTs sync; leituras report/channels/campaigns/events mantêm resolução de tenant.
- Meta: criação exige platform_admin; configure/discover/validate/save/activate/link/select/sync/refresh-token/disconnect exigem role; backfill exige autoridade de plataforma/agência e tenant. Conexão manual por token já estava retirada (410), sem nova desativação.
- Cinco rotas cron Meta têm autenticação **de máquina**, não papel de usuário: `_require_cron_secret` antes do runner. Bearer de viewer não substitui segredo de cron; contrato existente é 401 sem segredo quando configurado, não 403 de role. Não alterado.
- Shopify OAuth: seleção, sync, reconcile e disconnect exigem role; início exige agência; status mantém viewer. FBITS: connect, sync canônico/legado e disconnect exigem role antes de agendar trabalho.
- Google OAuth: seleção GA4/Ads, sync e disconnect exigem role; início exige role. Callbacks usam state ligado a usuário/tenant e não são POSTs de refresh autenticados por papel. Leitura de status/conexões e descoberta autorizada de recursos mantêm contrato existente; renovação técnica de credencial durante leitura OAuth não foi reclassificada como sync de dados nem alterada nesta tarefa.
- Fachada atual exige role para os quatro providers. Metas mantêm GET autorizado e CRUD administrativo, cobertos na suíte existente.

Novo arquivo necessário e justificado: `server/tests/test_legacy_refresh_authorization.py`, sete testes HTTP, sem IO real. O teste enumera todos os POST/PUT/PATCH/DELETE dos seis routers auditados, exceto cron de máquina e endpoint já retirado; expande os quatro providers da fachada: **32 casos por matriz viewer e admin de outro tenant**. Asserta 403, nenhum mock de sync/agendamento chamado e nenhum acesso inesperado ao DB. Testa ainda 12 caminhos admin de sync atuais/legados, leituras Google/Meta/Saúde com tenant, OAuth start recusado antes de criar estado, GA4 recusado antes da resolução de conexão e GET de identidade mutante recusado para viewer/outro tenant, permitido ao admin.

**Não basta publicar os arquivos do checkout original.** Ele preserva o guard GA4 paralelo na ordem antiga e ainda permite o GET de identidade mutante ao viewer. O teste novo evidencia essa diferença; o primeiro ensaio no checkout detectou a ordem GA4. As correções finais dessas rotas existem na árvore isolada e no patch seletivo abaixo. Nenhum resultado verde da árvore isolada foi atribuído ao checkout original.

### Manifesto publicável proposto e plano de integração

Manifesto exato proposto: **39 arquivos**, isto é, os 36 listados na seção “Arquivos desta missão e Git”, sem exclusões, mais:
- `server/tests/test_legacy_refresh_authorization.py` (novo, checkout e árvore isolada);
- `server/routes/google.py` (**versão da árvore isolada**, nunca staging integral do arquivo paralelo original);
- `server/routes/meta_legacy.py` (**versão da árvore isolada**, nunca staging integral do arquivo paralelo original).

Os dois arquivos de rotas não ficam excluídos desse manifesto: são dependências funcionais explícitas. Os outros seis arquivos paralelos e os hunks que não pertençam a esta integração permanecem fora do pacote. Não alterei a referência original de 36, para preservar a rastreabilidade; esta seção define a lista nova proposta.

Artefatos locais preparados:
- `/tmp/mugo-stability-publish-files.json`: lista literal dos 39 caminhos;
- `/tmp/mugo-stability-legacy-permissions.patch`: somente os hunks de autorização das duas rotas contra HEAD;
- `/tmp/mugo-stability-release-39.patch`: pacote completo contra HEAD, incluindo testes e este relatório;
- `/tmp/mugo-stability-release-39-sha256.json`: hashes das versões publicáveis.

Plano explícito, **não executado no checkout original**: conferir HEAD e hashes; abrir checkout limpo isolado dessa base pelo fluxo autorizado; verificar/aplicar o patch completo, que já contém as rotas e nunca precisa copiar os arquivos paralelos; conferir exatamente 39 diffs e o manifesto/hashes; repetir checks antes de staging explícito sob nova autorização. Coordenar os dois hunks sobrepostos com o responsável pelo trabalho paralelo para evitar reaplicação futura. Não aplicar o patch completo sobre o checkout sujo nem sobrescrever google.py/meta_legacy.py nele. Não incluir os oito diffs inteiros para contornar o conflito.

### Validação real desta rodada

Na árvore publicável isolada, sem os outros diffs paralelos:
- Regressões direcionadas (sete testes de autorização + cinco de release + seis de finalização HTTP): **18 passaram**, log `/tmp/mugo-blockers-isolated-targeted.log`.
- Suíte backend final: **1.544 passaram**, `APP_ENV=production PATH=/tmp/mugo-memory-venv/bin:$PATH npm run test:backend`, log `/tmp/mugo-blockers-isolated-backend-final.log`.
- Suíte frontend completa: **665 passaram em 97 arquivos**, executada via npm test; log `/tmp/mugo-blockers-isolated-suite.log`. Esse npm test também passou 1.542 backend antes da inclusão das duas últimas regressões; o backend foi repetido após essas inclusões.
- `npm run lint`, `npm run typecheck`, `npm run build`: exit 0 na árvore isolada; logs `/tmp/mugo-blockers-isolated-{lint,typecheck,build}.log`. Avisos Node/jsdom e tempo de Terser não foram falhas de build.
- `APP_ENV=production /tmp/mugo-memory-venv/bin/python -m compileall -q server`: exit 0 na árvore isolada.
- `git diff --check`: exit 0 no checkout original; validação adicional do patch completo por `git apply --check --whitespace=error-all` em base limpa preparada para conferência, sem staging.

A diferença de contagem em relação aos 1.539/666 do checkout compartilhado anterior é esperada: a árvore isolada remove testes acrescentados pelos diffs paralelos de onboarding/plataforma/navegação e acrescenta as 13 novas regressões desta rodada. Não houve remoção desses arquivos/testes no checkout original. Ajustes intermediários do harness (expansão do placeholder provider, argumentos posicionais e mock de leitura) foram corrigidos antes dos resultados finais. A tentativa inicial de git diff --check na árvore sem .git não é validação válida (exit 129); foi substituída pela conferência do patch contra base limpa e pelo diff --check do checkout original.

### Preservação, riscos restantes e veredito

Arquivos efetivamente editados **nesta rodada no checkout original**: `server/services/ads_sync.py`, `server/tests/test_ads_sync_resilience.py`, `docs/stability-release-audit.md`; novo `server/tests/test_legacy_refresh_authorization.py`. Os demais 33 arquivos da lista de 36 não receberam alterações nesta rodada. As duas rotas só foram editadas na área isolada. Oito diffs paralelos e arquivos não rastreados anteriores continuam byte a byte iguais às referências. HEAD esperado e index vazio preservados.

Instrumentação do commit 35e138b mantida: prints de diagnóstico da fachada iguais em AST à base, Request ID/origem/classe/resultado por fonte preservados, documento meta-refresh-502-audit sem diff e todos os testes anteriores mantidos. O evento de conclusão de release recebeu apenas o campo explícito released; nenhuma mensagem de exceção, token, payload ou dado pessoal novo é registrado.

**Os dois defeitos de código estão corrigidos na árvore integrada e suas regressões passam. Permanece o bloqueio de integração do checkout original. NO-GO para commit/push da antiga lista de 36 ou do checkout sujo.** O pacote isolado de 39 é o candidato técnico validado para integração e nova revisão/autorização; não declarar GO de publicação enquanto essas versões das duas rotas não fizerem parte do artefato efetivamente aprovado. Não há necessidade de migration, mudança de RLS/OAuth ou novo serviço para essas correções. Homologação real, margem de memória no Render, causa histórica do 502 e procedimento remoto da Amalie continuam pendentes como documentado anteriormente.


## Integração final validada — 20/10/2026

**Este parecer substitui o NO-GO de integração anterior: GO técnico para commit e push exclusivamente do candidato integrado de 39 arquivos desta área, mediante nova autorização. Não foi executado commit/push. O checkout original continua sujo e não deve ser usado para staging integral das rotas. GO de produção/estabilidade no Render não foi concedido.**

### Integridade e área recuperável

Artefatos de entrada encontrados, sem reconstrução por suposição: patch de 164.143 bytes, SHA256 `3223d05b07a2940665bef0a61ff46fa879526f36f4544ea9d0966e47f0d6b2e0`; manifesto com exatamente 39 caminhos únicos; JSON de hashes com as mesmas 39 chaves. O relatório original coincidiu com o hash recebido. Base/HEAD conferidos: `35e138b8ed1b67cba77606a4724c5e66458e6348`, branch main, index vazio.

Foi criado um clone local independente e recuperável, sem hardlinks ou alternates, na área indicada abaixo. O patch passou `git apply --check --whitespace=error-all` e foi aplicado somente nesse clone. **Os 39 arquivos aplicados coincidiram integralmente com os hashes do candidato de entrada antes deste adendo documental.** Nenhum código foi reconstruído, acrescentado ou refatorado nesta integração.

Snapshot original em `original-state/`: HEAD/branch, status completo, patch binário do worktree, patch conjunto e hashes individuais dos oito diffs, cópia e hashes de todos os arquivos não rastreados existentes. Nenhum arquivo original foi editado, nem este relatório no checkout original. Não houve reset, checkout destrutivo, staging ou alteração do index. O origin do clone foi alinhado ao origin original apenas por configuração Git local; nenhum fetch, ls-remote ou push foi realizado. A ponta remota atual não foi consultada.

### Integração seletiva das rotas e conflitos

Comparação de três versões (HEAD, paralelo original e candidato) executada com `git merge-file -p`, salvando as saídas sem escrever no original. Não houve conflito textual nem marcador de conflito. Houve **uma sobreposição semântica resolvida explicitamente**:

| Arquivo | Alteração paralela preservada | Resolução final |
| --- | --- | --- |
| server/routes/google.py | Import de require_client_role e bloqueio de viewer no Google Ads/GA4 | Google Ads mantém o guard paralelo. No GA4, a proteção é antecipada para antes de _ga4_request_context. O merge automático gerava guard duplicado após o contexto; essa duplicação não foi incorporada, pois a autoridade já foi conferida antes. Nenhuma outra mudança paralela existia nesse arquivo na referência registrada |
| server/routes/meta_legacy.py | require_client_role em api_refresh_all, também usado por /api/ig/sync | Hunk paralelo mantido. Acrescentado guard do candidato em api_instagram_debug_identity, cujo helper pode persistir configuração. O merge de três versões já coincidiu com o candidato; nenhuma mudança paralela foi descartada |

Auditoria por AST contra HEAD confirmou que somente quatro funções das rotas mudaram: `google_ads_sync`, `ga4_sync`, `api_refresh_all`, `api_instagram_debug_identity`. Import de require_client_role no Google é a única adaptação adicional de import. Fluxos OAuth, callbacks, schemas e RLS não foram alterados. O conteúdo final dessas rotas é idêntico ao candidato fornecido e incorpora semanticamente todas as proteções paralelas legítimas encontradas.

Regressões HTTP confirmaram viewer 403 antes de sync/escrita, GA4 403 antes de resolver conexão, GET de identidade mutante 403 sem discovery, admin próprio tenant autorizado e tenant incorreto recusado. Leituras de Google, Meta e Saúde continuam autorizadas ao viewer com isolamento. A matriz cobre 32 mutações atuais/legadas; cron por segredo de máquina e a antiga rota já retirada continuam com seus contratos próprios documentados, sem desativação nova.

### Testes na versão efetivamente integrada

Todos os comandos abaixo rodaram no novo clone integrado, não na árvore temporária anterior. APP_ENV=production foi usado nos comandos Python para evitar carregamento de dotenv. Nenhuma chamada de provider/banco real.

| Verificação | Resultado | Evidência em artifacts/ |
| --- | --- | --- |
| Regressões cleanup Ads, finalização HTTP e autorização legada | 18 testes aprovados | tests-regression.log |
| npm test: suíte frontend completa | 665 testes / 97 arquivos aprovados | tests-full.log |
| npm test: suíte backend completa | 1.544 testes aprovados | tests-full.log |
| npm run lint | exit 0 | lint.log |
| npm run typecheck | exit 0 | typecheck.log |
| npm run build | exit 0; aviso de tempo de Terser, sem erro | build.log |
| Python 3.13: compileall -q server | exit 0 | Comando executado no clone integrado |
| git diff --check | exit 0 no clone integrado e no original | Conferência repetida após o adendo |
| Aplicabilidade/whitespace do patch final e reconstrução por hashes | Conferidos em base limpa separada | final-integrated.patch e final-sha256.json |

O symlink temporário de node_modules, usado somente para executar as ferramentas instaladas, apareceu inicialmente como não rastreado devido à regra node_modules/ não ignorar symlink. Foi identificado e removido após os checks. **Não é alteração publicável e não existe no estado final.** Depois dessa remoção, o conjunto de arquivos modificados/novos do clone corresponde exatamente aos 39 caminhos. Build e caches gerados são ignorados e não entram no patch.

Instrumentação 502 conferida: prints de diagnóstico da fachada iguais em AST ao commit 35e138b; documento meta-refresh-502-audit byte a byte igual ao HEAD; todos os nomes de testes anteriores de resiliência Ads preservados e executados. O campo released do cleanup permanece no candidato, distinguindo confirmação da RPC de sucesso persistido. Não foi acrescentado log de mensagem sensível, payload, token ou dado pessoal nesta integração.

### Manifesto final e comparação

Manifesto final exato, 39 caminhos:
- `docs/stability-release-audit.md`
- `server/routes/goals.py`
- `server/routes/integrations.py`
- `server/services/ads_sync.py`
- `server/services/client_lifecycle.py`
- `server/services/clients.py`
- `server/services/cron_jobs.py`
- `server/services/memory_budget.py`
- `server/services/meta_backfill.py`
- `server/services/provider_refresh.py`
- `server/tests/cron_fixtures.py`
- `server/tests/test_ads_sync_resilience.py`
- `server/tests/test_cron_automation.py`
- `server/tests/test_fbits_automatic_sync.py`
- `server/tests/test_goals.py`
- `server/tests/test_meta_backfill.py`
- `server/tests/test_provider_refresh.py`
- `server/tests/test_shopify_reconciliation_cron.py`
- `server/tests/test_stability_release.py`
- `src/App.onboardingNavigation.test.tsx`
- `src/App.tsx`
- `src/app/DataHealthContext.test.tsx`
- `src/app/DataHealthContext.tsx`
- `src/app/api.ecommerceSync.test.ts`
- `src/app/api.ts`
- `src/app/syncOrchestrator.test.ts`
- `src/app/syncOrchestrator.ts`
- `src/pages/Dashboard.channelReport.test.tsx`
- `src/pages/Dashboard.tsx`
- `src/pages/Ecommerce.test.tsx`
- `src/pages/Ecommerce.tsx`
- `src/pages/GoogleAnalytics.refresh.test.tsx`
- `src/pages/GoogleAnalytics.test.tsx`
- `src/pages/GoogleAnalytics.tsx`
- `src/pages/Shopify.test.tsx`
- `src/pages/Shopify.tsx`
- `server/tests/test_legacy_refresh_authorization.py`
- `server/routes/google.py`
- `server/routes/meta_legacy.py`

Comparação com o candidato anterior: **38 arquivos idênticos em SHA256; somente docs/stability-release-audit.md difere**, pelo acréscimo deste relatório de integração. Zero mudança de código/teste após a aplicação e validação do candidato. Não há dependência ausente de outro diff paralelo para os guards publicados. Nenhuma migration nova/modificada; nenhum arquivo publicável fora dos 39.

Artefatos finais em artifacts/:
- `final-manifest.json`: array exato dos 39 caminhos;
- `final-sha256.json`: SHA256 de cada versão final, incluindo este relatório;
- `final-integrated.patch`: conteúdo completo final contra a base conferida;
- `final-verification.json`: integridade, preservação e comparação final;
- `route-integration.json` e saídas three-way: evidência das sobreposições;
- `code-audit.json`: conjunto de caminhos, funções de rotas e instrumentação;
- logs de testes/lint/typecheck/build citados acima.

Oito diffs originais permanecem preservados no checkout original. Para publicação, os hunks de autorização de Google/Meta foram incorporados seletivamente às versões finais, sem incluir seus arquivos sujos integrais. **Seis arquivos paralelos continuam completamente fora do commit proposto**: `.gitignore`, `server/services/invitations.py`, `server/tests/test_meta_onboarding_authorization.py`, `server/tests/test_platform_admin.py`, `src/components/shell/AppNavigation.test.tsx`, `src/design-review/ReviewApp.tsx`. Não foi identificada necessidade de publicá-los como dependência; a suíte integrada passou sem eles. As proteções desses dois arquivos de rotas incorporadas não sofreram regressão nos cenários de viewer/admin/tenant executados.

### Publicação futura e rollback

Após nova autorização, usar exclusivamente a área integrada ou reconstrução conferida do patch final sobre a mesma base. Revalidar base, manifesto, hashes, index e origem de push; staging futuro deve usar somente os 39 caminhos explícitos. Não aplicar o patch no original sujo, não usar git add . / -A e não incluir as seis alterações paralelas restantes. Se o remoto tiver avançado, interromper e revisar a integração contra a nova base; nenhuma compatibilidade com uma ponta remota desconhecida foi presumida.

Ordem proposta: backend e crons com client_lifecycle antes do frontend que depende de GET /api/clients; conferir schemas existentes por operador autorizado, sem aplicar migration automaticamente. Requisitos de ambiente e roteiro de homologação anteriores continuam válidos. Este GO atesta conteúdo local integrado/testado, não provisionamento, memória real no Render ou resolução histórica do 502.

Rollback antes de commit: abandonar a área integrada, conservando snapshot e checkout original intactos. Após futuro commit autorizado: reverter somente esse commit/pacote em checkout limpo e pelo fluxo aprovado; não resetar o original nem apagar dados, conexões, jobs ou snapshots. Coordenar frontend antes do backend para evitar frontend novo usando backend antigo. Rever a política viewer se o backend anterior voltar a permitir refresh. Reativação da Amalie e retomada de slices skipped/error são decisões independentes e não fazem parte deste rollback.

**Veredito: GO técnico para commit e push do candidato integrado exato de 39 arquivos, exclusivamente após nova autorização.** Nenhum conflito pendente, diferença de hash inexplicada, teste reprovado ou dependência paralela omitida foi encontrado nesta integração. Não executar publicação a partir do checkout original sujo. Homologação real e liberação aos clientes permanecem pendentes; nenhum incidente de produção foi declarado resolvido.

Área recuperável desta integração: `/var/folders/rq/bbb1jwkd2pj1l9c4d1j0kwtw0000gn/T/mugo-final-integration-vjhw_ia_`.
