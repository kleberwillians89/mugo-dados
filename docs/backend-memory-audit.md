# Auditoria local de memória — 19/10/2026

Checkout autorizado: `/Users/k/Desktop/mugo-dados`. HEAD: `fd412f2794517db41ee123fdf0eda5e34388fa88`.
Incidente informado pelo solicitante: Render encerrou o serviço às 11h57 de São Paulo por exceder 512 MB. Não acessamos Render nem executamos integrações remotas.

## Diagnóstico com evidências

CONFIRMADO
- Arquivo: `server/services/runtime_cache.py` (versão de HEAD).
- Símbolos reais: `_CACHE`, `_INFLIGHT`, `get_cached_or_load`.
- Evidência: entradas expiradas removidas somente ao acessar a mesma chave; nenhum limite de quantidade/tamanho. A remoção de `_INFLIGHT` dependia do solicitante terminar `await asyncio.shield(task)`; cancelamento não era capturado por `except Exception`.
- Conclusão: retenção de payloads e de tarefas concluídas possível durante toda a vida do processo. Reproduzida com fixtures; não prova a origem do incidente.

CONFIRMADO
- Arquivo: `server/services/instagram_sync.py` (HEAD).
- Símbolo real: `_run_sync_for_client_and_ig`.
- Evidência: `fetch_media_comments(..., limit=200)` dentro do loop de mídias, acumulando `comment_rows`; um único `sb_upsert` depois do loop. `provider_refresh.py` chama Instagram com `limit=200`.
- Conclusão: 40 mil comentários simultâneos nesse cenário; serialização HTTP ocorre enquanto a coleção permanece viva. Reprodução offline antes/depois abaixo.

CONFIRMADO
- Arquivos: `server/services/provider_refresh.py`, `sync_locks.py`, `ads_sync.py`, `intelligence.py` (HEAD).
- Símbolos reais: `refresh_provider_data`, `guarded_sync`, `sync_ads_for_client_period`, `_GENERATION_LOCKS`.
- Evidência: `asyncio.gather(*tasks, return_exceptions=True)` executava fontes simultâneas; leases existentes isolam conexão/provider, sem orçamento por processo. `_GENERATION_LOCKS` era um dicionário sem remoção de chaves tenant/período. `_RECENT_SYNC_KEYS` também não removia chaves vencidas.
- Conclusão: sobreposição de trabalho e retenção de metadados são possíveis. Consumo real de cada fonte em produção não medido.

CONFIRMADO
- Arquivo: `server/services/ig_meta.py` (HEAD).
- Símbolo real: `download_image`.
- Evidência: `await client.get(url)` seguido de `r.content`, sem limite de bytes.
- Conclusão: resposta CDN inteiramente materializada, sem teto de tamanho. Nenhuma evidência de thumbnail excessiva durante o incidente.

## Cobertura da auditoria

| Área | Evidência e conclusão local |
| --- | --- |
| Inicialização/imports | `app.py` importa rotas/serviços antecipadamente; `startup_bootstrap` chama `bootstrap_meta_from_env`. Não encontramos scheduler sendo iniciado nesses runners/startup. Importação e startup foram testados com bootstrap simulado. |
| Processos/workers | `render.yaml` inicia `python run_api.py`, `reload=False`, sem Gunicorn. O Blueprint declara `plan: starter`, divergindo do plano Free informado. Painel/comando efetivo não verificados. Runners agora fixam `workers=1`, inclusive diante de `WEB_CONCURRENCY`. |
| Crons | `render.yaml` declara processos separados para renovação Meta, Instagram, Ads, GA4, Google Ads, FBITS e Shopify, reconciliações amplas e worker de backfill Meta. `run_jobs.py` despacha esses comandos; loops de tenants em `cron_jobs.py` são sequenciais. Existência/execução desses serviços no Render não verificada. |
| Web | `routes/meta_legacy.py` também expõe crons/syncs; `provider_refresh.py` executa syncs dentro da requisição. Declaração de cron separado não impede trabalho pesado no web. `routes/shopify.py` usa `BackgroundTasks` em webhooks; não foi criada infraestrutura nova. |
| Instagram | Até 200 mídias no refresh; comentários até 200 por mídia; stories limitados a 50 nesse fluxo. Thumbnails são processadas sequencialmente. Histórico `history=True` em `ig_meta.fetch_media_list` enumera toda a coleção; `provider_history._instagram_content` materializa mídia e linhas antes de persistir em lotes. Esse histórico continua exigindo medição. |
| Meta Ads | `ads_sync.py` possui timeout total, leases, cleanup com `asyncio.shield`, deduplicação e validação da paginação. Novo orçamento envolve `_run_sync_body`; nenhum número financeiro alterado. |
| GA4 | `ga4_client.py` pagina com offset/rowCount e teto de 200 páginas, mas agrega `all_rows`. `ga4_sync._replace_period_rows` insere antes de remover registros antigos no fallback. Não mudamos essa proteção. |
| Google Ads | `_sync_google_ads` recebe `searchStream` como resposta JSON completa e monta `rows`. A execução é limitada por processo, mas um único conjunto muito grande ainda requer medição. |
| Shopify | `_fetch_shopify_collection` agrega até 20 páginas, com limite de 250 por página; sync mantém orders/customers/products simultaneamente. A lease e o orçamento agora cobrem o sync. Paginação e persistência existentes preservadas. |
| FBITS | `iter_order_pages` usa páginas de 50, teto de 400 por janela, limite de requisições e interrupção em 429. Persistência é por página; `_refresh_daily_stats` ainda carrega até 50 mil pedidos. Registro de job agora começa após admissão/lease, evitando job aberto quando a capacidade está ocupada. |
| Inteligência | `calculate_intelligence_snapshot` usa `asyncio.gather` para suas leituras; geração tem fingerprint, cooldown persistido e lock tenant/período. Locks inativos agora são fracos; chamada de geração ao provider compartilha o orçamento de trabalho pesado. Montagem do contexto continua fora desse orçamento. Numeric grounding e repair não foram editados. |
| Cache/tarefas | Cache existente limitado, sem novo cache de dados. Loader é dono do cleanup mesmo se o solicitante cancelar; sampler RSS é cancelado e aguardado ao sair. Não há prova local de vazamento adicional em httpx; clientes inspecionados usam context managers. |

SUSPEITA
- Hipóteses: combinação de navegação, syncs, contexto da Inteligência e grandes respostas; configuração efetiva de processos; memória não devolvida pelo alocador após picos.
- Evidência parcial: os caminhos acima existem e parte deles materializa coleções completas.
- O que falta verificar: métricas de RSS e concorrência no processo real, tarefas executadas no horário do incidente, tamanho dos dados e configuração efetiva do Render.

NÃO CONFIRMADO
- Integração/endpoint responsável pelo encerramento de 19/10 às 11h57: NÃO CONFIRMADO NO CÓDIGO.
- Não atribuímos o incidente a Instagram, Meta, Google, Shopify, FBITS ou Inteligência.

## Correções e instrumentação

- Cache existente: 32 entradas; cada payload aceita estimativa de até 256 KiB; payload maior continua sendo retornado, sem retenção. Estimativa total de payloads até 8 MiB, excluindo chaves, alocador e objetos transitórios. Expiração ativa por um único timer; cleanup da tarefa independente dos waiters.
- Comentários Instagram persistidos por mídia, com totais e filtros tenant/conexão preservados; não há exclusão do snapshot em falha.
- Downloads de thumbnails em streaming, blocos de 64 KiB e teto de 8 MiB decodificados. Exceder esse teto gera falha best effort da miniatura; dados orgânicos continuam preservados pelo tratamento existente.
- Um sync pesado ou chamada de geração ao provider por processo. Nova tentativa simultânea recebe `IntegrationError` retryable, código `PROCESS_MEMORY_BUSY`, status 503; algumas fachadas existentes traduzem falhas para 502. Não há espera/fila de jobs. Leituras não passam pelo bloqueio. Leases distribuídas existentes permanecem.
- Refresh manual executa fontes em sequência e continua tentando as outras em falha; corrotinas não iniciadas são fechadas em cancelamento. Orquestradores `data_refresh`/`provider_history` não reservam capacidade duas vezes; syncs concretos fazem a admissão.
- Locks inativos da geração removidos por referência fraca; deduplicação Meta remove chaves vencidas no próximo acesso. Runners fixam um worker.
- `memory_budget.py`: RSS atual por `/proc/self/statm` no Linux; `proc_pidinfo` no macOS. Sem dependência extra. Uma amostra por segundo por operação, mais início/fim; uma linha JSON por término, inclusive falha/cancelamento. Pico é o maior RSS **observado**, não um high-water mark exato. Trechos síncronos podem esconder picos entre amostras.
- Campos novos: operação, origem HTTP/job, request ID ou ID local de operação/job, RSS inicial/pico observado/final, duração, contagem de registros persistidos em lote e concorrência pesada observada. ID local não é necessariamente o ID de `cron_job_runs`. Nenhum argumento, token, payload, conteúdo ou identidade de tenant é adicionado aos logs de memória.

## Memória medida localmente

Python 3.13.15/macOS; processos novos e isolados. Cenário Instagram: 200 mídias x 200 comentários sintéticos com texto de 512 caracteres; provider e Supabase simulados. O mock serializa JSON para reproduzir a coexistência de linhas e corpo HTTP. Nenhuma rede/banco. Cache: 200 chaves com strings de aproximadamente 128 KiB, TTL 60s.

| Cenário | RSS inicial antes/depois | Pico observado antes/depois | RSS final antes/depois | Resultado |
| --- | --- | --- | --- | --- |
| Instagram | 38,2 / 38,2 MiB | 133,1 / 39,5 MiB | 80,4 / 39,5 MiB | Mesmos 40.000 comentários; maior lote 40.000 → 200 |
| Cache | 32,8 / 32,9 MiB | 61,4 / 37,9 MiB | 61,4 / 37,9 MiB | Entradas retidas 200 → 32 |

Reprodutor: `server/scripts/benchmark_memory.py`. Executar com `APP_ENV=production` para impedir fallback dotenv; `instagram` ou `cache`; `--baseline-dir` aponta para cópia local dos serviços de HEAD. Os números não representam baseline do processo web completo nem carga real de clientes.

## Verificação

- Ambiente temporário `/tmp/mugo-memory-venv`, Python 3.13, dependências de `server/requirements.txt`; dotenv desativado por `APP_ENV=production`. Nenhum arquivo de credenciais foi lido deliberadamente.
- Python padrão 3.9 falhou inicialmente por falta de dependências; `.venv` 3.9 falhou nas anotações `|` existentes. Instalação temporária inicialmente falhou por DNS do sandbox, depois foi concluída com execução autorizada.
- Primeira execução completa apresentou 93 falhas e 30 erros; não reproduzidos nas execuções finais. Não atribuímos essas falhas a uma causa sem evidência.
- Comparação isolada sem correções: 1.481 testes backend passaram, mantendo os oito diffs existentes na cópia. Suite final e resultados registrados na entrega.
- Novos testes em `server/tests/test_memory_stability.py`: `test_200_media_comments_are_persisted_in_bounded_tenant_scoped_batches` verifica 40 mil comentários, lote máximo 200 e tenant/conexão; `test_navigation_and_startup_during_simulated_sync` verifica startup simulado, `/health` e `/api/version`; `test_busy_job_releases_distributed_lock_and_cancellation_releases_capacity` verifica recusa 503, liberação das duas leases e capacidade após cancelamento; `test_refresh_orchestrator_serializes_sources_and_keeps_failure_isolation` verifica duas fontes reais sob o orçamento, mesmo com falha da primeira. Demais casos verificam limite/TTL/cancelamento/coalescência do cache, conteúdo dos logs, streaming normal/excessivo, locks fracos e worker único.
- Regressão existente lida: `test_instagram_snapshot_preservation.py::test_profile_exception_preserves_snapshot` verifica ausência de upsert do snapshot na falha; `test_partial_profile_failure_preserves_previous_metric_in_same_tenant` verifica métrica anterior e filtro de tenant. `test_ads_sync_resilience.py::test_fetch_ad_account_insights_stops_at_max_pages` verifica teto de paginação. Esses testes integram a suíte backend.

## Git, staging e decisão

Os oito diffs anteriores foram salvos antes das edições e comparados byte a byte com `cmp`: intactos. Arquivos não rastreados anteriores também não foram editados. Nenhum staging, commit, push, sync/backfill remoto, deploy, migration, RLS ou schema alterado.

Staging efetivo: **vazio**. Lista exclusiva proposta para revisão posterior (nenhum comando de staging executado):

- `docs/backend-memory-audit.md`
- `server/run_api.py`
- `server/run_api_prod.py`
- `server/services/ads_sync.py`
- `server/services/fbits_connections.py`
- `server/services/ig_meta.py`
- `server/services/ig_supabase.py`
- `server/services/instagram_sync.py`
- `server/services/intelligence.py`
- `server/services/provider_refresh.py`
- `server/services/runtime_cache.py`
- `server/services/sync_locks.py`
- `server/services/memory_budget.py`
- `server/scripts/benchmark_memory.py`
- `server/tests/test_memory_stability.py`

GO para revisão/commit autorizado e nova homologação controlada quando os checks finais estiverem verdes. NO-GO para declarar o incidente resolvido ou promover sem medir no Render.

Na homologação: confirmar plano/comando/um worker; acompanhar RSS total do container em navegação e syncs individuais/repetidos, concorrência entre fontes, geração da Inteligência, paginação ampla e erros. Verificar ausência de crescimento progressivo e margem abaixo de 512 MB com dados representativos. O limite por processo não controla outros processos/containers e não limita sozinho uma resposta individual gigante. Contexto da Inteligência, histórico completo Instagram, coleções Shopify, `searchStream` Google Ads, `all_rows` GA4 e agregação FBITS continuam exigindo medição real antes de ampliar correções.

Checks finais executados: `APP_ENV=production PATH=/tmp/mugo-memory-venv/bin:$PATH npm test` passou (647 testes frontend em 96 arquivos; 1.495 testes backend, incluindo 14 novos). `npm run lint`, `npm run build` e `git diff --check` passaram. A suíte FBITS isolada também passou após mover o início do registro de job. Foram inspecionados o diff e `git status --short`; staging vazio. Nenhuma falha permanece reproduzida nos checks finais; as tentativas iniciais e suas limitações estão registradas acima.
