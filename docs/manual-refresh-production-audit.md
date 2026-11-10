# Auditoria de refresh FBITS / Meta — 05/10/2026

## Evidência recebida e limite

O anexo relata Google funcionando, chamadas Graph `/insights` e `/comments` com 200 e GETs FBITS dashboard/orders com 200 e `cache_hit=true`. Não contém a linha do POST de refresh, status, horários, logs de persistência/projeção ou resposta do read model. Os números do anexo não foram incorporados aos testes.

Não há comprovação da versão efetivamente publicada. Não executei smoke remoto, alteração de banco, deploy, commit ou push. Os resultados abaixo são auditoria e regressões locais.

## META — CONFIRMADO

- Arquivo: `src/pages/Dashboard.tsx` / `src/hooks/dashboard/useDashboardSummary.ts`.
- Símbolos: `onRefresh`, `reloadSummary`, `autoPrimaryKeyRef`.
- Evidência: o refresh anterior chamava apenas `dashboardSnapshot.refetch()`. `dash`, mídias e comentários exibidos são armazenados separadamente por `useDashboardSummary`. O efeito automático retorna quando `autoPrimaryKeyRef.current === requestKey`, mesmo com um snapshot novo no contexto.
- Conclusão: atualizar o contexto não substituía o resumo orgânico nem relia mídias/comentários. A correção passa explicitamente o snapshot retornado para `reloadSummary`, evitando também usar o closure anterior antes de um rerender.

- Arquivo: `src/app/DashboardDataContext.tsx`.
- Símbolo: `loadSnapshot` / `inFlightSnapshots`.
- Evidência: uma requisição existente do mesmo tenant era reutilizada, inclusive no refresh manual.
- Conclusão: a releitura podia consumir uma consulta iniciada antes do sync. Meta agora usa a opção `afterCurrent`, aguarda essa consulta e faz uma nova. Outros consumidores mantêm a chamada padrão.

- Arquivo: `src/pages/Dashboard.tsx`.
- Símbolo: `onRefresh`.
- Evidência: o retorno `null` de `refetch()` não era verificado antes de registrar sucesso.
- Conclusão: falha na releitura agora produz erro e preserva os dados disponíveis. Falhas das leituras secundárias também retornam `null`, mantendo os valores anteriores da seção que falhou.

- Arquivo: `server/services/ads_sync.py` / `server/services/provider_refresh.py`.
- Símbolos: `sync_ads_for_client_period`, `_RECENT_SYNC_KEYS`, `refresh_provider_data`.
- Evidência: o sync pago devolve `ok=false, skipped=true, reason=duplicate` na janela de deduplicação de cinco minutos. A fachada aguardava ambas as fontes e convertia esse resultado em 502; o frontend não relia dados após erro, mesmo com sucesso orgânico.
- Conclusão: o cooldown existente continua ativo, mas agora a fachada retorna 429 com `Retry-After` restante. Erros 429 das tarefas Meta também são preservados como cooldown explícito.

- Arquivo: `server/services/instagram_sync.py`.
- Símbolos: `_run_sync_for_client_and_ig`, `_sync_instagram_connection`.
- Evidência: coleta, upserts e projeção são aguardados. A coleta orgânica grava `snapshot_date` de hoje em UTC e projeta somente esse dia. Antes, `_mark_connection_success` podia executar mesmo quando `snapshot_saved=false`.
- Conclusão: snapshot não persistido agora interrompe o fluxo antes de marcar sucesso. Um período histórico fechado pode manter os mesmos totais apesar da atualização de hoje; `data_max_available` é cobertura de datas e não horário de refresh. A migration local projeta `last_success_at=now()`; a versão dessa RPC em produção NÃO CONFIRMADO NO CÓDIGO.

### Pipeline Meta antes/depois

Antes: Graph → persistência → projeção → conclusão de ambas as fontes → refetch do contexto, potencialmente antigo → resumo/mídias antigos; `null` da releitura podia terminar como sucesso. Deduplicação paga podia bloquear a releitura após sucesso orgânico.

Depois: Graph → persistência → projeção/freshness → conclusão de ambas as fontes → nova consulta após qualquer leitura anterior → resumo construído com o snapshot retornado + GETs mídias/comentários/stories → UI. Cooldown retorna 429 explícito. Falhas preservam a última leitura das seções afetadas.

### SUSPEITA em produção

- Hipótese: uma ou mais falhas acima explicam o sintoma relatado.
- Evidência parcial: o anexo relata Graph 200 sem mudança visível; o defeito do resumo antigo foi reproduzido localmente.
- Falta: POST completo, resultado de cada fonte, persistência/projeção e resposta de `dashboard_source_snapshots` na versão publicada.

Causa exclusiva do incidente de produção: **NÃO CONFIRMADO NO CÓDIGO.**

## FBITS — CONFIRMADO

- Arquivo: `src/pages/Ecommerce.tsx`, `src/app/api.ts`, `server/routes/integrations.py`, `server/services/provider_refresh.py`.
- Símbolos: `syncNow`, `refreshProviderData`, `refresh_client_provider`, `refresh_provider_data`.
- Evidência: Ecommerce aguarda `runExclusiveSync` → POST `/api/clients/{tenant}/data-refresh/fbits` → `sync_fbits_connection` → `invalidate_official_kpis` → resposta, antes de `reloadFbits({force:true})` e releitura de conexões.
- Conclusão: no código local esse botão não faz somente GET. `runExclusiveSync` deduplica apenas chamadas concorrentes e libera a entrada ao terminar; não possui cache de sucesso.

- Arquivo: `src/components/FbitsIntegrationPanel.tsx`, `src/app/api.ts`, `server/routes/fbits.py`.
- Símbolos: `syncNow`, `syncFbitsConnection`, `fbits_tenant_sync`, `_schedule_tenant_sync`.
- Evidência: o painel administrativo chamava a rota antiga `/fbits/sync`, recebia 202 com `scheduled=true` e executava `onChanged()` sem aguardar a tarefa em background.
- Conclusão: esse botão não usava a fachada implementada. Foi ligado à fachada existente com o mesmo `runExclusiveSync` do Ecommerce; `onChanged()` e a mensagem de conclusão agora ocorrem após o resultado. Conexão inicial e endpoints legados continuam existentes.

- Arquivo: `server/services/fbits_connections.py`.
- Símbolo: `sync_fbits_connection`.
- Evidência: não há retorno por considerar os dados frescos. O sync usa janelas históricas ou marcador incremental, consulta `/pedidos`, persiste pedidos/itens/estatísticas e atualiza `metadata.last_success_at` / `last_sync_at`. Cooldown persistido impede a chamada antes de acessar credenciais; 429 interrompe o ciclo e é propagado.
- Conclusão: não foi encontrado skip silencioso nesse fluxo. Corrigida perda do `retry_after` ao converter um 429 externo em `IntegrationError`; a rota agora recebe o prazo original. O período enviado pela fachada não força reimportação histórica: o serviço usa seu marcador existente.

### Explicação exata de `cache_hit=true`

- Arquivo: `server/services/fbits_official_kpis.py` / `server/services/runtime_cache.py`.
- Símbolos: `fetch_official_kpis`, `get_cached_or_load`, `invalidate_namespace`.
- Evidência: `cache_hit=true` ocorre somente quando `_CACHE[full_key]` tem entrada não expirada. Os KPIs executivos são obtidos de `/dashboard/faturamento`, separadamente dos pedidos; o cache é em memória de processo, por tenant/período, TTL de 300 segundos. A invalidação remove entradas `_CACHE` do processo atual e não remove `_INFLIGHT`.
- Conclusão: essa linha comprova reutilização de KPIs, não comprova sync nem sua ausência. Um GET posterior pode reutilizar uma entrada repopulada por outra leitura. A invalidação em um processo também não limpa os demais. O primeiro GET após sync bem-sucedido e invalidação, no mesmo processo e sem outra leitura concorrente, não deve reutilizar a entrada antiga: a regressão confirma isso.

### SUSPEITA em produção

- Hipóteses: caminho administrativo em background; versão publicada diferente; POST bloqueado/falhou; GET servido por outro processo; leitura concorrente repopulando cache.
- Evidência parcial: somente GETs/cache foram fornecidos; o caminho administrativo em background e as limitações de cache existem no código.
- Falta: POST/status/horários e etapas do sync. Foram adicionados PID nos logs de início e dos KPIs para ajudar a confrontar processos, sem assumir que PID sozinho identifica instâncias distintas.

Qual dessas hipóteses causou o `cache_hit=true` observado: **NÃO CONFIRMADO NO CÓDIGO.** O cache não foi desligado nem redesenhado sem evidência.

### Pipeline FBITS antes/depois

Ecommerce: já aguardava sync → persistência/freshness → invalidação → GETs. Acrescentados logs de clique, provider call, persistência, freshness, cache, conclusão e cooldown.

Admin antes: POST legado → 202/agendamento → releitura de status → sync em background.

Admin depois: POST da fachada existente → sync → persistência/freshness → invalidação → resposta → releitura de status.

## Provas locais e limitações dos testes

`server/tests/test_manual_refresh_pipeline.py`:

- `test_fbits_real_sync_persists_advances_freshness_and_expires_old_kpis`: executa o sync real com HTTP FBITS simulado e banco em memória; semeia cache antigo, recebe pedido novo, verifica persistência/estatísticas/freshness, relê KPIs e `build_fbits_summary` com valor novo.
- `test_meta_provider_persist_projection_freshness_in_order`: executa coleta/agregação/upserts reais do serviço com funções de Graph simuladas, verifica o novo snapshot/mídia e a ordem persistência → projeção → sucesso. RPC e banco são simulados, não homologados remotamente.
- `test_meta_duplicate_is_explicit_cooldown_even_after_organic_success`: sucesso orgânico + deduplicação paga retornam 429 e prazo restante.

`src/hooks/dashboard/useDashboardSummary.refresh.test.tsx`: `refresh substitui resumo e mídias antigos usando o snapshot retornado após sync` verifica números novos e timestamp novo na saída renderizada do hook real.

`src/app/DashboardDataContext.test.tsx`: `releitura após sync espera consulta antiga e inicia quatro queries novas` cobre a race com leitura anterior.

`src/pages/Dashboard.channelReport.test.tsx`: `Meta espera sync terminar antes da releitura e entrega snapshot novo ao resumo` e `Meta não anuncia sucesso quando a releitura falha` exercitam o handler do botão com tarefas pendentes/mocks de hooks.

`src/pages/Ecommerce.test.tsx`: `FBITS aguarda sync completo antes de reler dashboard/orders e substituir números` verifica ordem e substituição da UI com hooks reais e API simulada.

`src/components/FbitsIntegrationPanel.test.tsx`: `admin aguarda fachada FBITS antes de reler status` verifica espera e mensagem de conclusão.

Nenhum teste local prova token, chamadas externas ou persistência em produção. O relatório anterior não autorizava inferir homologação a partir de mocks. A antiga cobertura de fachada mockava os serviços de sync; o contrato Meta anterior era uma inspeção textual e não detectava o resumo que permanecia antigo.

## Verificação

- `npm test`: 568 frontend / 1300 backend, exit 0.
- `npm run lint`, `npm run typecheck`: exit 0.
- `npm run build` e `git diff --check`: exit 0.
- Diff revisado em `/tmp/mugo-production-refresh.diff`: inclui alterações anteriores nos arquivos já modificados; não representa somente esta rodada.
- `run_manual_refresh_pipeline_mutations.py`: 13/13 detectadas, em cópias temporárias. Remove provider, persistência, invalidação/freshness; antecipa releitura nos três handlers; mantém resumo/freshness antigos; reutiliza leitura anterior.
- Uma mutação inicial do provider Meta sobreviveu porque a asserção não cobria followers; o teste foi fortalecido com o valor persistido, e o rerun completo detectou todas as mutações.

## GO / NO-GO

| Provider | Local | Produção |
|---|---|---|
| Meta | Correções e regressões aprovadas localmente | **NO-GO para declarar resolvido**: falta correlacionar o smoke com POST, persistência/RPC e nova resposta/UI |
| FBITS | Fachada validada; admin alinhado; cache e cooldown preservados | **NO-GO para declarar resolvido**: a causa exata do cache do smoke ainda depende do POST e logs completos |

Nenhuma mudança nova em Google, Google Ads, OAuth, client_access, Customer 360, Intelligence, migrations/RLS ou isolamento. A opção de releitura adicionada ao contexto compartilhado é acionada apenas pelo handler Meta; os consumidores padrão não mudaram. Alterações preexistentes desses arquivos permanecem no workspace.
