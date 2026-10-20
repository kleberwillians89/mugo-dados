# P0 — divergência entre conclusão Meta Ads e HTTP 502

Auditoria local em 20/10/2026, checkout Desktop autorizado. Base do pacote: `fdd268ab91bbc3865083c4d8e24bae7121b9b448`. Sem refresh remoto, acesso a credenciais, migration, staging, commit, push ou deploy.

## Evidência e limite da conclusão

CONFIRMADO
- Arquivos: `server/services/ads_sync.py`, `provider_refresh.py`, `sync_locks.py`, `server/routes/integrations.py`.
- Símbolos: `sync_ads_for_client_period`, `_finish_job_run_reliably`, `_release_lock_reliably`, `refresh_provider_data`, `guarded_sync`, `refresh_client_provider`.
- Evidência: fluxo abaixo lido integralmente nas fronteiras de conclusão; regressão HTTP executa sync Ads, fachada, rota e finalizadores reais com provider/banco simulados.
- Conclusão: `meta_ads.manual_refresh_done status=success` é conclusão do corpo Ads, anterior à finalização do job e ao finally. Não é confirmação do status HTTP nem do refresh conjunto Meta.

NÃO CONFIRMADO
- A causa da requisição de produção e a composição exata dos 90 round trips. NÃO CONFIRMADO NO CÓDIGO.
- Os Request IDs e resumos HTTP foram fornecidos no complemento; a sequência de etapas foi informada no pedido cirúrgico. Ainda não foram fornecidos os erros por fonte, stack traces ou dependências detalhadas. Nenhum acesso remoto foi realizado. Os testes reproduzem caminhos possíveis, não identificam retroativamente qual exceção ocorreu em produção.

## Caminho exato do retorno e das exceções

1. `refresh_provider_data` entra em `guarded_sync(data_refresh, meta)`, adquire cooldown e resolve Instagram e Ads. Aguarda fontes sequencialmente, mantendo isolamento de falhas.
2. O corpo `_run_sync_body` de Ads persiste, lê de volta, projeta e marca a conexão; imprime `meta_ads.manual_refresh_done status=success`. Ainda constrói o resultado e sai do decorator de memória. Falha nessa saída também pode ser capturada pelo sync.
3. `sync_ads_for_client_period` aguarda o corpo com `asyncio.wait_for`, finaliza `cron_job_runs` com `_finish_job_run_reliably`, imprime `job_finish_complete` e prepara retorno. Uma falha de finalização após o log de sucesso entra no `except Exception`, que tenta registrar erro de conexão/job e relança; o log anterior continua no histórico. A auditoria não mudou nenhuma dessas escritas.
4. Antes de retornar ou propagar exceção, executa o `finally`: `_release_lock_reliably` e `ads_sync.lock_release_complete`. Esse log aparece também no caminho de erro. O helper captura exceções ordinárias da RPC, registra somente tipo e usa TTL como fallback; assim, `lock_release_complete` indica fim do helper, não comprova que o banco liberou o lock. Timeout do shield pode deixar a tarefa de cleanup em execução. No ramo `CancelledError`, `await task` pode propagar uma exceção do cleanup; ela não passa pelo handler irmão `except Exception`. Esses comportamentos existentes não foram alterados sem evidência do incidente.
5. Depois de `lock_release_complete`, a expressão `await task` da fachada recebe o dicionário Ads **ou uma exceção propagada**. `except Exception as exc` guarda a exceção em `results`. Não há outra chamada Ads de banco entre esse log e esse retorno.
6. O `finally` da fachada chama `.close()` nas corrotinas para encerrar fontes não iniciadas após cancelamento; fechar corrotinas já concluídas é permitido. `CancelledError` não é convertido em resultado normal pelo `except Exception`. Uma exceção de `.close()` escaparia antes da classificação; não é o caminho explícito de HTTP 502 por resultado.
7. Para cada fonte, o código verifica resultado e cooldown. Depois, qualquer exceção, `ok=False`, `partial=True`, `sync_outcome=partial` ou `read_model_refreshed=False` causa `meta.manual_refresh_error stage=sync_or_projection status=502`, seguido de `HTTPException(502, ...)`, identificando fontes malsucedidas. Isso inclui Instagram parcial mesmo com Ads totalmente concluído. Um resultado Ads completo e sem falhas das demais fontes não satisfaz esse predicado.
8. Mesmo no sucesso, a saída do `async with` ainda executa o `finally` de `guarded_sync`, liberando o lock da fachada. Esse release não captura exceções; falha aqui pode substituir retorno/erro anterior. No app FastAPI mínimo do teste, gera HTTP 500, não o `meta.manual_refresh_error stage=sync_or_projection` de 502. Não atribuir esse caso ao incidente sem o log exato e eventual camada de proxy.
9. A rota trata `IntegrationError` (com tratamento específico para 429); a `HTTPException(502)` da fachada segue para o FastAPI. Não foi introduzido fallback de HTTP 200 nem reclassificação de resultado persistido.

Instrumentação mínima adicionada em `provider_refresh.py`: log de falha de fonte agora cobre também `partial=True` e projeção falsa (antes o log individual não acompanhava todo o predicado do 502), com `request_id`, `source`, `stage=source_result`, código seguro, status, `outcome` e `error_type`. Exceções são identificadas pelo nome da classe, sem texto bruto, payload, token ou conteúdo do cliente. O predicado que decide HTTP não foi modificado. Assim será possível distinguir retorno parcial de uma exceção capturada sem inventar causa. `request_id=-` significa execução sem contexto de request.

## Duas liberações da RPC

| Responsável | Chave | Papel |
| --- | --- | --- |
| `ads_sync` finally / `_release_lock_reliably` | `sync:meta_ads:<connection_id>` | Serializa sync Ads da conexão, inclusive por entradas diferentes |
| `guarded_sync` da fachada | `sync:data_refresh:meta` | Serializa refresh conjunto Meta do tenant |
| Cooldown | `refresh_cooldown:meta` | Adquirido, não liberado no final; expira naturalmente |

A RPC `release_client_job_lock` em `supabase/migrations/20260305_000001_multi_tenant_and_features.sql` atualiza validade apenas para `client_id` **e** `job_name` iguais. São dois responsáveis e dois escopos distintos, não redundância da mesma chave. Repetir a RPC com a mesma chave não gera erro lógico explícito nesse SQL, mas rede/permissões ainda podem falhar. A regression verifica nomes e ordem das duas chamadas, sem liberação do cooldown. Não removemos nenhum lock.

## Os 90 round trips

O contador `RequestPerformance.round_trips` é incrementado por `transport_started`. Os pontos encontrados são `ig_supabase._request` (cada tentativa REST, inclusive RPC) e `auth.require_user_id` (Supabase Auth). A propriedade de resumo chama-se `supabase_round_trips`. `meta_http.meta_get_json`, downloads e `sb_upload_public` não chamam esse contador. Logo, se o número relatado vem desse campo, 90 não significa 90 chamadas Graph nem soma de toda a rede. Uma chamada RPC conta uma vez, não cada operação SQL interna. Requisições posteriores de Saúde dos Dados têm Request IDs próprios e não devem ser somadas ao POST.

| Grupo real | Necessidade / quantidade variável | Repetição ou oportunidade |
| --- | --- | --- |
| Auth, memberships, autorização tenant | Necessário; contexto já memoiza auth/tenant/membership na mesma requisição | Não remover autorização; separar nos logs por `phase` |
| Leases da fachada e cooldown | 3 RPCs no sucesso: acquire fachada, acquire cooldown, release fachada | Escopos distintos, necessários para serialização/cooldown |
| Resolução orgânica e paga | Duas consultas iniciais do mesmo tenant em `resolve_connection_for_scope` sem id | Colunas e leitura repetidas; potencial de reúso por operação, sem cache global. Não otimizado nesta etapa |
| Resolução/validação no sync e no token | Ads resolve conexão explícita; token carrega conexão e atualiza validação; Instagram também resolve sua conexão | Sobreposição parcial, mas projeção operacional não contém credencial: não substituir leitura de token cegamente |
| Job Ads | INSERT inicial e PATCH terminal, mais tentativas/compatibilidade em falha | Necessários para rastrear conclusão; PATCH pode ter retry de transporte e retry do finalizador |
| Lease Ads | acquire e release, duas RPCs | Necessário e diferente do lock da fachada |
| Persistência Ads | Um POST por tabela não vazia no caminho normal, quatro tabelas possíveis | Fallback de schema/on_conflict e remoção de colunas podem repetir POSTs; identificar pelos logs `upsert_fallback`, não removê-los sem conferir schema real |
| Readback Ads | Quatro consultas de `stat_date`, até 50 mil linhas por tabela | Verificação usada para outcome; tabela vazia pode causar duas consultas extras pelas variantes com/sem `act_`. Candidata a count/existence limitado no futuro; não eliminar prova de persistência nem mudar semântica nesta auditoria |
| Projeção e status Ads | RPC de read model e PATCH da conexão | Necessários; projeção SQL não implica round trip por linha |
| Instagram comentários | Até um POST `ig_comments` por mídia com comentários, lote <=200 | Muitos POSTs podem ser legítimos, com chaves distintas. Não juntar todos os comentários em memória para reduzir round trips |
| Instagram métricas indisponíveis | GET anterior de `ig_media` por mídia afetada | Preserva métricas anteriores; possível prefetch em lotes limitado, exige benchmark e equivalência semântica |
| Instagram perfil/mídias/status/projeção | Upserts de mídias/snapshot, PATCH conexão e RPC de projeção | Necessários; retries de schema podem repetir chamadas |
| Thumbnails | Download e upload fora do contador; cada sucesso faz PATCH `ig_media` que entra no contador | Até uma gravação por thumbnail. Detectar URL já persistida pode evitar trabalho futuro, mas não há evidência suficiente para alterar nesta etapa |
| Graph Ads | Insights conta/campanha/ad paginados; catálogo filtrado **e** catálogo sem filtro; insights por anúncio turbinado | Fora do contador de Supabase. Catálogo sem filtro é consultado mesmo quando o filtrado já foi escolhido: trabalho potencialmente evitável. Não alterar cobertura/catalogação sem teste específico |
| Transporte | GET/PATCH podem tentar até 3 vezes; POST normalmente 1 no transporte | Distinguir retry de chamada funcional repetida; por si só não prova duplicidade de sync |

Não há dados suficientes para decompor exatamente os 90 em cada grupo. A contagem varia com mídias, comentários, thumbnails, schema, tabelas vazias e falhas de transporte. Não afirmar que Instagram, catálogo, RPC duplicada ou retries causaram esse total sem o detalhamento por Request ID. Para fechar: contar `performance.dependency` da mesma requisição por dependency/operation/status, cruzar `supabase.request_retry`, `upsert_fallback`, `job_finish_retry` e número de mídias efetivamente persistidas. Nenhuma nova concorrência pesada foi adicionada.

## Regressão e validação

Arquivo `server/tests/test_ads_sync_resilience.py`, classe `ManualRefreshHttpFinalizationTests`:
- `test_completed_ads_returns_http_success_after_job_finish_and_both_distinct_releases`: POST real da rota/fachada/sync com provider/DB simulados; confirma persistência chamada, projeção, sucesso da conexão, job terminal com 1 linha, dois locks distintos e JSON HTTP 200 coerente.
- `test_ads_success_does_not_mask_partial_instagram_http_502`: Ads e job concluem; Instagram parcial continua HTTP 502 e mensagem identifica somente Instagram. Não reescreve status Ads.
- `test_terminal_job_failure_after_body_success_is_not_forced_to_200`: falha de finalização mantém HTTP 502, sem texto bruto na resposta.
- `test_outer_release_exception_overrides_return_but_does_not_rewrite_ads_job`: falha na liberação da fachada resulta 500 no ASGI, mantendo conclusão Ads persistida no fixture.

19 testes do arquivo de resiliência passaram. Suíte completa: **1.526 backend e 658 frontend em 97 arquivos**. Lint, typecheck e build passaram. Logs locais `/tmp/mugo-502-specific.log`, `/tmp/mugo-502-full-tests.log`, `/tmp/mugo-502-lint.log`, `/tmp/mugo-502-types.log`, `/tmp/mugo-502-build.log`.

Alterações desta etapa: `server/services/provider_refresh.py`, `server/tests/test_ads_sync_resilience.py`, este relatório. Sem mudança em `ads_sync`, `sync_locks`, resultado persistido, OAuth, schema ou mecanismo de memória. Sem staging/commit/push/deploy. Causa de produção permanece pendente da evidência solicitada; não declarar incidente resolvido.

## Complemento: resumos de produção fornecidos pelo usuário

Anexo recebido após a auditoria inicial, referente a 19/10/2026: foram lidos 16 resumos `performance.request`, sendo 5 HTTP 200, 8 HTTP 409 e 3 HTTP 502. O anexo contém apenas resumos HTTP e linhas de `api.integration_error` dos 409; não contém `manual_refresh_done`, `job_finish_complete`, `lock_release_complete`, `manual_refresh_error` nem `performance.dependency`. A evidência agora confirma os resultados e contagens abaixo, mas ainda não a exceção ou a fonte que levou ao 502.

| Request ID | HTTP | Duração | Round trips |
| --- | --- | --- | --- |
| `d9b23cbcaec84a689e041308a37d6189` | 200 | 164.532,52 ms | 90 |
| `0caf737a87b84ac098785cd221fb6cfb` | 502 | 201.680,30 ms | 90 |
| `61db3a30100f4014af23c2149cf2ee90` | 502 | 143.854,92 ms | 90 |
| `e6667c101d61472db36d7e50794e4bef` | 502 | 8.584,39 ms | 17 |

CONFIRMADO: 90 round trips aparecem tanto em sucesso quanto em falha; portanto, o número isolado não explica nem comprova a causa do 502. Há também falha com 17 chamadas. As durações diferentes não comprovam um timeout comum. `unclassified_ms` é tempo fora das fases instrumentadas, não uma medição exclusiva de Graph ou de processamento CPU; fases aninhadas também não devem ser somadas como tempos independentes.

Um 409 de `provider=data_refresh code=SYNC_ALREADY_RUNNING`, iniciado às 21:11:12 UTC, está dentro do intervalo da requisição `0caf...`, iniciada às 21:09:17 UTC e com duração de aproximadamente 201,68 segundos. Isso é compatível com bloqueio de uma segunda tentativa enquanto a primeira seguia em andamento; não comprova lock órfão nem liberação duplicada. Outros 409 não têm o início do possível detentor no anexo e não podem ser diagnosticados como órfãos por esses resumos.

Pendência específica: obter o corpo dos logs das requisições `0caf...` e `61db...` (e, para comparação, `d9b...`), com falhas por fonte, finalização Ads, liberação e dependências. Sem essas linhas, a divergência entre o log interno de sucesso Ads e o HTTP 502 da mesma requisição permanece NÃO CONFIRMADO NO CÓDIGO. Nenhuma nova alteração funcional foi feita a partir desses resumos.

## Diagnóstico cirúrgico — conclusão com a sequência completa informada

O usuário informou agora a sequência `provider_done → persistence_complete → refresh_complete → freshness_updated → manual_refresh_done(success) → job_finish_complete(success) → lock_release_complete → meta.manual_refresh_error(502)`, associada a `0caf737a87b84ac098785cd221fb6cfb`. Tratamos essa sequência como evidência fornecida pelo usuário; não alegamos acesso aos logs históricos do Render. O arquivo anexado anteriormente contém apenas resumos para esse Request ID e `61db3a30100f4014af23c2149cf2ee90`, sem stack trace, erro por fonte ou resposta HTTP detalhada. Também falta confirmar o SHA efetivamente executado nesses eventos para equiparar integralmente o checkout à produção.

**Causa raiz histórica: ainda inconclusiva. Mecanismo do 502: comprovado e reproduzido.** A fachada atual guarda a exceção da fonte em `provider_refresh.py:107–108`, continua a fonte seguinte e só depois avalia todos os resultados em `:141`. A conversão explícita é `raise HTTPException(502, ...)` em `:146` (linha 137 no HEAD sem instrumentação). A sequência completa informada restringe o diagnóstico: a finalização Ads com sucesso e o término de seu finally são compatíveis com um erro/parcial do Instagram armazenado anteriormente. Não é necessário haver uma nova exceção depois da conclusão Ads; a decisão HTTP pode ocorrer depois, usando a falha já capturada. **Não comprova qual exceção/flag ocorreu nas requisições históricas.**

Após `ads_sync.py:1875` (`manual_refresh_done`), ainda são executados: construção do dict `result`; segunda classificação de outcome; atualização da deduplicação local; retorno do corpo; finalizador do decorator de memória; retorno de `wait_for`; finalização do job em `:1959`; `job_finish_complete` em `:1973`; atribuições `job_run_id`/`job_status`; retorno; finally com release e log em `:2084–2093`; retomada na fachada em `:106`; fechamento das corrotinas; avaliação de resultados/cooldown; decisão 502. Com `job_finish_complete(success)` e `lock_release_complete` já observados na mesma execução, falha de finalização do job é um cenário de teste alternativo, não a explicação comprovada dessa sequência completa.

Rota e serialização conferidas: `server/routes/integrations.py:63` chama `require_client_read` antes do refresh; `:67` aguarda a fachada. No sucesso, `provider_refresh.py:151–154` constrói apenas campos escalares e estados seguros. Esses comandos não são atingidos quando a classificação em `:141` decide 502. `server/app.py:187–214` preserva `HTTPException.status_code` e produz JSON com message/request_id; não transforma falha comum de serialização em 502. O handler de exceção não tratada em `app.py:264` devolve 500. O handler `IntegrationError` em `:217` preserva o status declarado. Não foi alterado nenhum handler.

A segunda RPC após `meta.manual_refresh_error` é explicada pelo `finally` do contexto externo `sync_locks.py:82–83`: ele roda também durante a propagação da HTTPException. No teste são exatamente duas liberações de chaves diferentes, não dois releases Ads: primeiro `sync:meta_ads:conn-1`, depois `sync:data_refresh:meta`. Uma linha histórica que cite apenas a função RPC, sem seus argumentos ou logs de lock, não demonstra duas liberações da mesma chave. Não removemos a proteção de nenhum escopo nem adicionamos chamadas RPC.

### Reprodução adicional e instrumentação final

`server/tests/test_ads_sync_resilience.py:425`, `ManualRefreshHttpFinalizationTests.test_instagram_exception_reproduces_502_after_successful_ads_finalization`:
- Instagram lança `ValueError` sintético; Ads real (com IO simulado) persiste, projeta, marca conexão e finaliza o job como success.
- Confere a ordem das linhas: sucesso Ads, job finalizado, release Ads, `lock_release_complete` com Request ID, erro agregado Meta, release externo.
- HTTP é 502 e identifica somente Instagram. Job Ads tem uma única finalização success; nenhum mark_error Ads é chamado. Não apaga nem altera o resultado concluído.
- Verifica redaction da mensagem sintética tanto na resposta quanto nos novos logs, e presença de fonte, tipo e origem da exceção. Também mantém o teste de Instagram parcial e o teste de sucesso completo HTTP 200.

Como a exceção histórica ainda não foi identificada, **somente instrumentação foi implementada**, sem correção funcional especulativa:
- `server/services/provider_refresh.py:86`: encaminha o Request ID já existente ao parâmetro de diagnóstico Ads; não altera resultado nem sincronização.
- `:115–131`: log de falhas acompanha todas as flags já usadas na decisão 502 e inclui source/outcome/error_type/error_origin; origem contém somente nome do arquivo, linha e função do último frame, sem stack source, texto de exceção, variáveis ou conteúdo do cliente.
- `:143`: inclui Request ID no log agregado 502. Decisão HTTP, persistência, locks, ordem sequencial e serialização permanecem iguais.

Nenhuma otimização dos 90 round trips foi implementada. Não atribuímos o erro ao total, ao tempo ou ao encerramento normal de 20/10. A interpretação histórica continua pendente de `source_result`/erro original/stack sanitizado ou flags do Instagram para os Request IDs completos acima. A instrumentação é local e ainda não está implantada, portanto não recupera retroativamente os eventos.

Veredito: **GO para revisão e commit especificamente da instrumentação/testes, somente com nova autorização; GO para planejar homologação controlada após revisão e autorização. NO-GO para declarar causa raiz histórica identificada, incidente resolvido ou correção funcional homologada.** Sem commit/push/deploy nesta etapa.

### Checks finais desta revisão cirúrgica

- `APP_ENV=production /tmp/mugo-memory-venv/bin/python -m unittest discover -s server/tests -p test_ads_sync_resilience.py`: **20 testes, OK**.
- Mesmo comando com `test_provider_refresh.py`: **24 testes, OK**.
- `APP_ENV=production PATH=/tmp/mugo-memory-venv/bin:$PATH npm test`: **1.527 backend e 658 frontend (97 arquivos), OK**.
- `npm run lint`, `npm run typecheck`, `npm run build`, `git diff --check`: **OK**. O build emitiu um aviso de depreciação do Node, sem falhar.
- Houve uma falha intermediária de expectativa exata em `test_meta_syncs_only_persisted_meta_sources_and_sanitizes_failure`: a nova chamada passava `request_id=None` sem contexto HTTP. Ajustado para encaminhar somente identificador existente, preservando a chamada sem contexto. O teste não foi afrouxado nem editado; as duas suítes foram novamente executadas e passaram.
- Logs desta rodada: `/tmp/mugo-502-surgical-tests.log`, `/tmp/mugo-502-surgical-provider.log`, `/tmp/mugo-502-surgical-full.log`, `/tmp/mugo-502-surgical-lint.log`, `/tmp/mugo-502-surgical-types.log`, `/tmp/mugo-502-surgical-build.log`.
- Git: branch `main`, HEAD `fdd268ab91bbc3865083c4d8e24bae7121b9b448`, index vazio; os oito diffs paralelos comparados byte a byte com as duas referências anteriores. Arquivos Ads/Instagram, locks, Saúde dos Dados, rota, cache e orçamento de memória idênticos ao HEAD. Mudanças acumuladas da auditoria limitadas à fachada, teste de resiliência e este relatório; nenhum arquivo paralelo incluído.
