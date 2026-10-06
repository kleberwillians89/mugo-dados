# P0 de leitura — evidência, correções e medição pendente

## Evidência de produção fornecida em 06/10/2026

Não foram fornecidos neste anexo timestamps de início, request IDs, parâmetros
completos, status de todas as respostas ou linhas de auth/Supabase correlacionadas.
Portanto a ordem e sobreposição do waterfall real não podem ser reconstruídas
com precisão. A tabela abaixo é a reconstrução parcial, sem inventar cronologia:

| Leitura | Endpoint total | Trabalho interno fornecido | Tempo restante |
| --- | --- | --- | --- |
| media | 21–29 s | 10 linhas/3,812 s ou 11 linhas/3,014 s | Não calculável por request sem correlação |
| comments, caso 1 | ~29,9 s | ~6,3 s, 10 mídias/28 comentários | ~23,6 s fora do serviço |
| comments, caso 2 | ~26,9 s | ~5,1 s, 11 mídias/13 comentários | ~21,8 s fora do serviço |
| monthly | ~20,8 s | ~2,721 s, 78 linhas/12 meses | ~18,079 s fora do trabalho reportado |
| goals | ~16,6 s | Não informado | Não distribuído |
| integrations | 22,294 s, 403 | Não informado | Não distribuído |

Poucas linhas também têm latência alta. Volume não explica sozinho essa
evidência. Saturação da dependência, auth lenta ou cold start não são causas
confirmadas. Origami/503 e Roove/Intelligence 502 permanecem sem diagnóstico;
o incidente numérico anterior da Curavino não explica Roove.

## Mapa confirmado no código atual

| Request | Consumer | Finalidade/período | First render? | Depois da mudança |
| --- | --- | --- | --- | --- |
| media | `Dashboard → useDashboardSummary` | Conteúdo/ranking/publicações da janela global | Não é necessário para KPIs de snapshots | Só ao visualizar Instagram, após o read model e conexão selecionada; paginação da janela |
| comments | `Dashboard → useDashboardSummary` | Comentários/top words; mesma janela, `include_media_linked=true` | Não | Só ao visualizar comentários; reaproveita media já carregada |
| monthly | `Dashboard → useDashboardMonthlyContent` | Agregados de conteúdo por mês | Não | Só ao visualizar histórico; janela selecionada, não 3650 dias |
| integrations | `Dashboard → useClientIntegrations` | Identificação de ativos/conexão | Secundário; guard administrativo | Viewer não solicita; cache válido reutilizado; outros papéis continuam sujeitos ao backend |
| goals | `App → GoalsSummary → useGoals` | Até três metas visíveis; progresso requer cálculo persistido | Não bloqueia snapshot | Só ao visualizar resumo; página Metas continua leitura direta da janela |
| daily/campaign/product/source read models | `DashboardDataProvider` | Base persistida da janela selecionada e tenant | Sim | Consultas limitadas à janela; comparação anterior explícita quando consumida |
| previous paid | `Dashboard → useDashboardPaid` | Narrativa visível de comparação no hero pago | Necessária para delta visível, não para valor atual | Usa janela anterior explícita/cache/read model; não solicita media/comments |

Não há chamadas em JSX para `useDashboardMedia`/`useDashboardComments` no código
atual. Os arquivos existem, mas não são consumidores montados desta navegação.
`Dashboard` monta somente uma instância de `useDashboardSummary`.
Os seletores de comparação mensal usam agregados de `monthlyRows`, sem chamar
media/comments por mês. Não há prefetch de julho/agosto nesses consumidores.

Logo a atribuição individual de julho repetido, agosto, outubro até hoje e
outubro inteiro a cada interação da produção é **NÃO CONFIRMADA NO CÓDIGO**.
Falta HAR com Initiator, início/fim, URL/params e versão implantada, além de
logs correlacionados. Não removemos uma finalidade desconhecida por hipótese.
No código anterior desta rodada, monthly realmente usava 3650 para histórico
independente da seleção. O requisito de 90 dias já o tornou limitado à janela;
o texto da tela foi alinhado a esse comportamento.

## Repetições comprovadas e correções

O logging de media/comments/monthly chama `_log_endpoint_call`, que validava o
bearer remotamente; `resolve_client_id` repetia a validação e, com conexão
explícita, `resolve_connection_id` a repetia novamente. Integrações passa por
`require_client_role`, que chama auth e depois `resolve_client_id`, repetindo
auth. Agora a mesma validação compartilha a Promise **somente no request**;
nova requisição revalida. Falha não se transforma em sucesso.

`sb_get_client_memberships` enriquecia cada membership com uma consulta
sequencial a `clients`. Guards só usam IDs/papéis, mas chegavam a pedir essa
lista repetidamente. Agora usam `sb_get_client_membership_roles`, sem nomes de
empresa; a apresentação de memberships mantém o enriquecimento original.
Resultado fica memoizado somente dentro daquele request, sem novo TTL de role.
Membership, owner/admin legado, agency e platform mantêm as decisões existentes.

Na UI, conexão ainda não resolvida podia gerar scope `-` seguido de scope
explícito. Requests secundários agora aguardam conexão selecionada e snapshot.
Efeitos automáticos são agendados em microtask cancelável, evitando replay
duplicado de efeitos em StrictMode. StrictMode está no entrypoint, mas não é
atribuído como causa das duplicações de produção.
Leituras idênticas em voo compartilham Promise via `readOnce`, com chave incluindo
tenant, conexão, janela, paginação e semântica. Cache válido evita releitura.
Refresh manual continua forçando releitura. Janela diferente não é duplicata.
Uma resposta atrasada não substitui o tenant atual.

## 403 de integrações: sequência real

`require_client_role → require_user_id → resolve_client_id → platform/agency →
membership do tenant → platform/agency → papel efetivo → 403`.
`get_client_connections` só é chamado depois da autorização; nenhum catálogo
de providers é carregado antes desse 403. A correção reduz trabalho do próprio
guard e elimina o request administrativo feito pelo viewer na página Meta.
Não libera viewer nem muda a rota para um guard permissivo.
Os 22,294 s dessa execução continuam sem breakdown comprovado.

## Round trips: estimativa estática, não medição

Para viewer/client_admin, tenant explícito, conexão explícita, schema moderno,
cache de plataforma frio, sem retry/fallback e uma página: `M` é quantidade de
memberships e `K` é quantidade de chunks de comentários ligados (até quatro).
Inclui Auth e REST; não inclui consultas diretas do navegador ao Supabase.

| Endpoint | Antes | Depois |
| --- | --- | --- |
| media | `9 + M` | `7` |
| monthly | `9 + M` | `7` |
| comments com linked | `10 + M + K` | `8 + K` |
| integrations negado por papel | `7 + 3M` | `4` |

Cache quente de platform reduz um round trip em ambos; service cache quente,
papel agency/platform, conexão ausente, paginação e retry mudam essas contas.
Mesmo depois, validação de conexão na rota e resolução semântica no serviço
continuam distintas; não eliminamos um guard supondo equivalência.

O anexo descreve cinco media, cinco comments, um monthly, um goals e
um integrations: 13 requests citados, não um inventário completo. Sem a quantidade
de metas, memberships, páginas e hits de cache, total real de round trips por
navegação é **NÃO CONFIRMADO**. Antes/depois real precisa da mesma navegação/HAR.
Aplicando apenas os caminhos frios da tabela aos 12 requests citados de
media/comments/monthly/integrations, o subtotal teórico é `111 + 14M + ΣK`.
Somar o custo de goals e demais consumidores. Isso não é um total medido:
cache compartilhado pode reduzi-lo e retry/paginação podem aumentá-lo.
Nos testes, uma janela em StrictMode demanda uma media e um comments; habilitar
comentários depois não repete media; rerender não repete ambos. Isso prova número
de chamadas, não latência de produção.

O catálogo de meses (`listMonthsByConnection`) alimentava apenas as opções de
comparação. Elas agora reutilizam os meses de `monthlyRows`, que já pertencem à
janela selecionada: nenhum request all-time adicional nem meses preenchidos
com zero apenas por existirem fora da janela. Notas já eram protegidas pela
flag `SHOW_PRESENTATION_EXTRAS`; não são atribuídas ao storm deste anexo.

## Instrumentação implantável, ainda não publicada

`[performance][request]` inclui request ID, início UTC, endpoint, tenant mascarado,
janela, status, duração, round trips e fases: auth, tenant, authorization,
membership, connection_validation/resolution e data_media/comments/monthly/goals/
integrations. `unclassified_ms` mostra tempo fora das fases externas medidas.
Fases aninhadas incluem seu tempo interno: **não somar todas as fases**.
Cache/loader compartilhado pode atender vários requests; considerar o mesmo
request ID no log da dependência, não duplicar sua latência na soma.

`[performance][dependency]` mede cada tentativa Auth/REST e informa fase,
operação, status, duração e quantidade de chamadas em voo no processo no início.
Não imprime bearer, argumentos, filtros, parâmetros completos, payload ou PII.
Tentativas e retries são contados; a concorrência não mede outros workers.
`[performance][first_useful_data]` no navegador mede do efeito inicial do scope
até o frame com snapshot disponível. Não mede carga da página antes da montagem
nem promete que todos os painéis secundários estejam completos.

Exportar os novos logs do Render e processar **localmente, sem credenciais**:

```bash
python server/scripts/summarize_request_performance.py /caminho/exportacao-sanitizada.log
```

O comando não foi executado com logs de produção. Produz waterfall por início,
round trips/fases por request e mediana/p95 por dependência/fase com concorrência
baixa (até duas em voo) versus alta. Coletar uma navegação isolada e outra com
requests concorrentes, mantendo tenant, período e cache comparáveis; correlação
não é prova de causalidade. Capturar também HAR sem Authorization/cookies e
logs do navegador para o first useful data.
Budget a verificar: alvo 1–3 s, teto 5 s; **ainda não certificado**.

## Impacto em 90 dias e limites do resultado

Persistência histórica de até 90 dias e comandos operacionais continuam no
[documento de histórico](provider-history-90-days.md). Selecionar 90 dias lê
fatos persistidos da janela; não dispara sync/backfill. Entrar na plataforma
não inicia automaticamente leitura de 90 dias se a seleção atual for menor.
Se 90 estiver salvo como seleção, a janela principal é essa; secundários ainda
ficam sob demanda. Instagram continua sem snapshots históricos fabricados.
Numeric grounding e repair não foram alterados.

**GO local condicionado às suites e checks finais. NO-GO para declarar resolvidos
os 20–30 s, certificar o budget ou encerrar Origami/Roove sem nova medição.**
Sem commit/push/deploy/migration/backfill remoto. Os oito diffs paralelos devem
continuar comparados byte a byte com o baseline anterior.

Validação final local: 631 testes frontend (92 arquivos, `--maxWorkers=2`),
1466 backend no venv, incluindo 32 de histórico e oito de diagnóstico.
Lint, typecheck, build e diff-check passaram. Numeric grounding/repair comparados
por AST com HEAD: quatro funções inalteradas. Index vazio; oito diffs paralelos
preservados byte a byte.
Uma execução frontend com mais workers estourou 5 s em Charts; repetição da suite
completa passou sem alterar esse teste nem aumentar timeout. Python do sistema
não possui todas as dependências (incluindo FastAPI); validação backend usa
`PATH=/tmp/mugo-refresh-venv/bin:$PATH npm run test:backend`.

## Pacote local combinado: 90 dias + performance

Os arquivos abaixo compõem este pacote local; os oito diffs paralelos não estão
incluídos. O comando é apenas uma referência futura, **não foi executado**.
Os arquivos compartilhados contêm mudanças das duas etapas: não separar os
commits por arquivo presumindo que cada diff pertença a apenas uma etapa.

```bash
git add -- \
  docs/provider-history-90-days.md \
  docs/read-performance-production-evidence.md \
  server/app.py \
  server/run_jobs.py \
  server/scripts/summarize_request_performance.py \
  server/services/ads_meta.py \
  server/services/ads_sync.py \
  server/services/auth.py \
  server/services/comments.py \
  server/services/connection_resolver.py \
  server/services/connections_service.py \
  server/services/ga4_client.py \
  server/services/ga4_reporting.py \
  server/services/ga4_sync.py \
  server/services/goals.py \
  server/services/google_ads.py \
  server/services/ig_dashboard.py \
  server/services/ig_meta.py \
  server/services/ig_supabase.py \
  server/services/intelligence.py \
  server/services/media.py \
  server/services/meta_backfill.py \
  server/services/provider_coverage.py \
  server/services/provider_history.py \
  server/services/request_performance.py \
  server/services/tenant.py \
  server/tests/test_integration_stabilization.py \
  server/tests/test_provider_history_90_days.py \
  server/tests/test_provider_refresh.py \
  server/tests/test_release_data_completeness.py \
  server/tests/test_request_performance.py \
  server/tests/test_safe_access_logs.py \
  src/app/DashboardDataContext.test.tsx \
  src/app/DashboardDataContext.tsx \
  src/app/PeriodContext.tsx \
  src/app/api.monthlyPeriod.test.ts \
  src/app/api.ts \
  src/app/types.ts \
  src/components/GoalsSummary.tsx \
  src/components/data/HeroFigure.tsx \
  src/components/data/KpiFigure.tsx \
  src/components/data/PeriodSelector.test.tsx \
  src/components/data/PeriodSelector.tsx \
  src/hooks/dashboard/readOnce.test.ts \
  src/hooks/dashboard/readOnce.ts \
  src/hooks/dashboard/useDashboardGa4.test.tsx \
  src/hooks/dashboard/useDashboardGa4.ts \
  src/hooks/dashboard/useDashboardMonthlyContent.test.tsx \
  src/hooks/dashboard/useDashboardMonthlyContent.ts \
  src/hooks/dashboard/useDashboardSummary.performance.test.tsx \
  src/hooks/dashboard/useDashboardSummary.ts \
  src/hooks/dashboard/useExecutiveDashboard.test.tsx \
  src/hooks/dashboard/useExecutiveDashboard.ts \
  src/hooks/useClientIntegrations.ts \
  src/hooks/useFirstUsefulData.ts \
  src/hooks/useGoals.ts \
  src/hooks/useSectionDemand.test.tsx \
  src/hooks/useSectionDemand.ts \
  src/pages/Dashboard.channelReport.test.tsx \
  src/pages/Dashboard.connectionRead.test.tsx \
  src/pages/Dashboard.refreshContract.test.ts \
  src/pages/Dashboard.tsx \
  src/pages/GoogleAnalytics.tsx \
  src/pages/Intelligence.tsx
```

Mensagem sugerida: `feat: add scoped 90-day history and reduce dashboard read amplification`

Diferenças paralelas preservadas, excluídas do comando:

- `.gitignore`
- `server/routes/google.py`
- `server/routes/meta_legacy.py`
- `server/services/invitations.py`
- `server/tests/test_meta_onboarding_authorization.py`
- `server/tests/test_platform_admin.py`
- `src/components/shell/AppNavigation.test.tsx`
- `src/design-review/ReviewApp.tsx`

Também preservados sem staging: `.opencode/`, `AGENTS.md` e os documentos prévios
`client-goals-release.md`, `manual-refresh-production-audit.md`,
`provider-refresh-release.md` e `release-final-adjustments.md`.

## Correção do gate de conexão em cache frio

A página resolve a conexão operacional por `GET /api/clients/{client_id}/connections`,
com tenant explícito e autorização de leitura existente. Não usa `/integrations`
para viewer e não consulta o catálogo genérico. Cache válido evita descoberta;
cache vazio faz uma leitura compartilhada em voo por tenant, inclusive StrictMode.
A seleção reutiliza `resolveOperationalMetaConnectionId`; nenhuma conexão é fixada.
Ausência/ambiguidade termina sem consultas secundárias; erro tem mensagem explícita.
Respostas atrasadas são descartadas após troca de tenant.

Snapshot principal continua independente. Media/comments/monthly somente começam
quando suas seções são demandadas e a conexão está resolvida. Os seis testes em
`src/pages/Dashboard.connectionRead.test.tsx` montam a página com hooks reais de
resumo/mensal, cache vazio e observer controlado; incluem viewer/admin, StrictMode,
cache preenchido, resposta antiga após troca de tenant, ausência e erro.

Essa correção não diagnostica o 403 de 22 s, Origami/503 ou Roove/Intelligence 502,
nem certifica o budget de produção. O read model principal ainda aguarda suas
quatro tabelas; monthly pode restaurar cache e depois reler. Seleção persistida
em 90 dias continua podendo ser restaurada na navegação.

Validação após a correção: 29 testes frontend relacionados (7 arquivos),
631 frontend completos (92 arquivos), 1466 backend completos; lint, typecheck,
build e diff-check passaram. Index vazio e oito diffs paralelos preservados.
Numeric grounding/repair: quatro funções idênticas a HEAD por AST.
