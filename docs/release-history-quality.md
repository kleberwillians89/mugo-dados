# Fase 2 — qualidade dos fatos e histórico de 90 dias

Nenhum sync/backfill remoto, migration ou escrita no banco foi executado.
Origami (503 simultâneos) e Roove (Intelligence 502) continuam não diagnosticados.
O request_id da Curavino não pertence a esses incidentes.

## Regras operacionais corrigidas

| Achado | Antes | Depois | Dados persistidos / recuperação |
| --- | --- | --- | --- |
| Meta Ads — paginação | O teto de 200 páginas interrompia a busca e devolvia lista parcial como se completa. | O teto continua protegendo contra paginação indefinida. URL/cursor repetido, next inválido ou next pendente no teto lançam `META_ADS_PAGINATION_INCOMPLETE` (502). Linhas idênticas não são duplicadas. | Não apaga fatos antigos. O worker não usa reconciliação de fatos antigos para converter esse erro em sucesso; até três tentativas, depois erro terminal. Janelas afetadas anteriormente precisam de nova coleta completa, não apenas reprojeção. |
| Google Ads — projeção | Ingestão concluída permitia `ok=True` mesmo com projeção `ok=False`. | Toda janela, inclusive vazia, exige projeção `ok=True`. Falha/exception gera `GOOGLE_ADS_PROJECTION_FAILED` (502); job e tentativa falham, freshness anterior permanece. | Upserts já concluídos ficam duráveis. Não há delete/clear. Reprojeção ou reexecução idempotente da mesma janela pode recuperar; nenhuma foi executada. |
| GA4 — usuários | Soma diária aparecia como usuários do período. | Relatórios mantêm campos numéricos legados, com `user_count_semantics=sum_of_daily_users` e rótulos de soma diária. O contexto executivo tem `users=null`, `users_status=unavailable` e `daily_user_sum` explícito. No read model, a soma é de `activeUsers`; no relatório bruto, `totalUsers`. | Sem alteração de fatos/schema. A Data API define usuários como distintos; não há IDs individuais nem agregado deduplicado do período persistidos. Sem deduplicação inventada. |
| Google Ads — REMOVED | Filtro pelo status atual excluía uma campanha removida mesmo com fatos no período. | Consulta mantém o filtro de data e inclui entidades removidas. | Não apaga fatos. Para recuperar fatos antes omitidos, é necessária futura reexecução das janelas afetadas. |

O Google documenta que a API inclui entidades removidas quando o filtro por status não é aplicado:
https://developers.google.com/google-ads/api/docs/reporting/uireports#common_differences

Semântica de `totalUsers`/`activeUsers`:
https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema

Não foram alterados `_is_number_supported`, `_number_candidates`, validator, schema da IA,
modelo ou limite de duas chamadas da recuperação numérica. A versão do contexto da análise
foi incrementada para evitar reutilizar análises construídas com a semântica anterior.

## Instagram: capacidade comprovada do fluxo atual

Classes: A = histórico por data; B = observação atual; C = cumulativa/não aditiva;
D = disponibilidade histórica limitada; E = não reconstruível pelo fluxo atual.
As classes podem coexistir (por exemplo, alcance diário observado é B/C).

| Métrica / campo usado | Endpoint atual | Parâmetros atuais (sem credenciais) | Granularidade / classe | Backfill real e limitação |
| --- | --- | --- | --- | --- |
| `followers_count`, `media_count`, metadados do perfil | `GET /{ig_user_id}` | `fields` | Atual, B; valores anteriores ausentes, E | Não reconstrói seguidores de dias passados. Crescimento somente entre observações persistidas comparáveis. |
| `reach` | `GET /{ig_user_id}/insights` | `metric=reach`, `period=day`, `metric_type=total_value`; sem since/until | Observação B; alcance único C | O fluxo não percorre datas. Não somar dias/mídias como alcance único do período. |
| `profile_views`, `website_clicks`, `total_interactions` | Mesmo endpoint | Uma métrica por chamada, `period=day`, `metric_type=total_value`; sem since/until | B no fluxo atual | Não há coletor por data. Só observações persistidas; 90 observações não provam 90 dias completos de atividade. |
| `accounts_engaged` | Mesmo endpoint | Mesmos parâmetros | B/C | Contagem de contas não aditiva; não deduplicar por soma. |
| `views`, fallback `impressions` | Mesmo endpoint | Mesmos parâmetros | B | O fluxo pode usar views como impressions. A origem/versão e a disponibilidade de cada métrica precisam ser verificadas antes de prometer história. |
| Quantidade de publicações, tipo, timestamp | `GET /{ig_user_id}/media` | `fields`, `limit`, `paging.next` | Publicação por timestamp, A/D | Pode selecionar publicações históricas realmente retornadas pela origem. Limite por quantidade não prova que todos os posts dos 90 dias foram coletados. Sem rotina nova de backfill nesta fase. |
| Feed: `reach`, `likes`, `comments`, `shares`, `saved`, `total_interactions`, `profile_visits` | `GET /{media_id}/insights` | `metric`; sem since/until | Observação acumulada por mídia, C/D | Permite desempenho observado das mídias publicadas no período, não atividade diária ocorrida nesse período. Reach somado entre posts não é alcance único. Likes/comments_count de `/media` também são observações atuais. |
| Reels: `views`, `reach`, `likes`, `comments`, `shares`, `saved`, `total_interactions`, `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time`, `reels_skip_rate` | Mesmo endpoint | `metric` por tipo; fallback individual por métrica | C/D | Tempo médio e taxa não são somáveis; disponibilidade depende da mídia/origem. Sem reconstrução de série diária. |
| Comentários: quantidade/timestamp/like_count | `GET /{media_id}/comments` | `fields`, `limit`, `paging.next` | Evento datado A/D; likes B | Somente comentários ainda retornados/persistidos. Não comprova histórico de comentários removidos nem completude de paginação por limite de quantidade. Nenhum texto pessoal entra no levantamento SQL. |
| Stories publicados e `impressions`, `reach`, `replies`, `shares`, `total_interactions`, `profile_activity` | `GET /{ig_user_id}/stories`, `GET /{story_id}/insights` | `fields`, `limit`; `metric` | D; expirados não coletados E no fluxo | Reutilizar somente observações realmente persistidas. Não fabricar histórico de Stories antigos. Não foi confirmado aqui um prazo universal de retenção por métrica. |
| Fallback pago: `impressions`, `reach`, `clicks`, `actions` | `GET /{ad_account_id}/insights` | `date_preset=last_30d`, `fields` | Período pago A/C | Não é histórico orgânico de 90 dias nem substitui os insights de perfil. |

O workspace oficial da Meta confirma paginação por tempo no User Insights, mas isso
não comprova disponibilidade de 90 dias para cada métrica/versão/permissão:
https://www.postman.com/meta/instagram/folder/u4g5a2a/instagram-api-with-facebook-login

**Não há métrica de perfil com backfill diário de 90 dias comprovado neste fluxo.**
Não foi implementado backfill novo: não há evidência suficiente para escolher métricas
reconstruíveis e seus limites atuais. Métricas sem observação devem ser tratadas como
`unavailable` em qualquer operação histórica futura; nunca copiar valores atuais para o passado.

Limitação adicional encontrada no mapeamento: `ig_dashboard.get_dashboard` possui fallback
que deriva séries de mídias por data de publicação e mistura métricas acumuladas nos totais
quando faltam snapshots. Esse fallback **não comprova snapshots diários ou alcance único** e
não pode ser usado para certificar 90 dias. Este documento explicita essa limitação; a rotina
não foi reaproveitada para criar um backfill. Não atribui os 503 de Origami a esse comportamento.

## Quatro dimensões independentes de qualidade

1. Coverage: fatos/datas presentes para um tenant + conexão + conta/propriedade + dataset.
2. Completeness: busca terminada sem truncamento, escopos corretos, métricas esperadas
   disponíveis e reconciliação com a origem. Dias sem linha não significam automaticamente zero.
3. Freshness: último sync válido da origem; última escrita de um fato pode ser parcial.
4. Projection: última projeção bem-sucedida do read model. É registrada atualmente por
   tenant/provider, não certifica isoladamente cada conta/propriedade.

Para 05/10/2026 em São Paulo, a janela inclusiva é 08/07/2026–05/10/2026.
Não há evidência de completude de produção ainda. A consulta read-only em
`docs/read-only-provider-coverage.sql` preserva contas/propriedades distintas, não retorna
payloads/PII/secrets, e deve ser executada manualmente pelo usuário no SQL Editor.
Resultado sem registro não prova provider não aplicável. Tenant não localizado exige UUID
confirmado; ausência de permissão/tabela não significa dataset vazio.

Não há migration necessária para este pacote. Uma futura persistência de usuários únicos
do GA4 por período/propriedade exigiria desenho próprio; não foi criada nesta correção.

## Arquivos e provas de regressão

| Achado | Arquivos de implementação / consumidores | Testes e risco coberto |
| --- | --- | --- |
| Meta Ads | `server/services/ads_meta.py`, `server/services/meta_backfill.py` | `test_release_data_completeness.py`: dez testes de paginação (uma/várias páginas, fim exato no teto, truncamento, repetição de URL/cursor, erro intermediário, duplicação, URL inválida, contexto do tenant). `test_ads_sync_resilience.py`: teste de teto ajustado e `test_truncated_dataset_never_persists_or_marks_sync_success_and_releases_lock`. `test_meta_backfill.py`: `test_pagination_failure_cannot_be_recovered_as_success_from_old_rows`, com tentativas 1, 2 e 3. |
| Google Ads | `server/services/google_ads.py` | Seis testes em `test_release_data_completeness.py` para sucesso, projeção false/exception, ingestão falha, janela vazia e REMOVED com gasto/conversões históricos. `test_google_ads_observability.py`: preservação do timestamp anterior e job error. `test_provider_refresh.py`: fachada falha e não invalida snapshot como atualizado. `test_google_ads_accounts_flow.py`: dois mocks de projeção ajustados a `ok=True`; sem alteração do teste de MCC/conta filha. |
| GA4 | `server/services/ga4_reporting.py`, `server/services/executive_dashboard.py`, `server/services/intelligence.py`, `src/app/api.ts`, `src/app/types.ts`, `src/hooks/dashboard/useDashboardGa4.ts`, `src/hooks/dashboard/useExecutiveDashboard.ts`, `src/components/dashboard/Ga4SiteBehaviorPanel.tsx`, `src/pages/GoogleAnalytics.tsx` | Três testes em `test_release_data_completeness.py`: 100+100 preservado como soma explícita, users únicos indisponíveis no contexto executivo, semântica correta nos períodos atual/anterior da Inteligência. Um teste novo em cada `GoogleAnalytics.test.tsx`, `useDashboardGa4.test.tsx` e `useExecutiveDashboard.test.tsx`. A suíte de numeric grounding/repair continua passando. Não há novo percentual de usuários únicos. |
| Instagram / SQL | Este documento e `docs/read-only-provider-coverage.sql`; código do provider não alterado | Dois testes novos em `test_instagram_snapshot_preservation.py` demonstram parâmetros atuais sem intervalo histórico e persistência de uma observação, sem preencher datas anteriores. Os testes existentes de preservação/isolamento também passaram. A consulta SQL não foi executada no banco; compatibilidade do schema remoto permanece pendente. |

25 testes backend novos e três frontend novos. Resultados finais:

- Backend relacionado (Meta Ads, Google Ads, GA4, Instagram, Inteligência, viewer,
  tenant isolation, refresh): 376 testes passaram.
- Frontend relacionado: 19 testes em quatro arquivos passaram, incluindo o teste
  existente de refresh que mantém cards/freshness e não relê snapshot parcial após erro.
- Backend completo: 1.426 testes passaram.
- Frontend completo: 609 testes em 85 arquivos passaram.
- Lint, typecheck, build e `git diff --check`: passaram.

Na primeira execução, três testes de Google Ads falharam porque o mock de projeção
não retornava `ok=True`; os mocks foram corrigidos e a suíte completa repetida passou.
O lint inicial identificou um efeito durante renderização em um teste novo; foi movido
para `useEffect`, e lint/typecheck/build foram repetidos com sucesso.

Nenhum dado já persistido foi alterado pelo agente. Nenhum backfill/reprojection foi
executado. Os oito diffs paralelos foram comparados byte a byte antes/depois, sem diferença.
Não houve staging, commit, push ou deploy.

Veredito: **GO LOCAL para os P0 corrigidos**, condicionado à revisão deste pacote.
**NO-GO para declarar histórico de 90 dias completo ou os incidentes de produção resolvidos.**
