# Histórico de até 90 dias — operação e limites

Implementação local. Nenhuma coleta ou consulta de produção foi executada nesta rodada.
Datas exemplificadas: 2026-07-08 a 2026-10-05, 90 dias inclusivos.

## Produto

O seletor compartilhado oferece 7, 30 e 90 dias, mês atual, mês anterior e
personalizado de 1 a 90 dias. Consultas do read model usam `client_id`,
`metric_date >= start` e `metric_date <= end`; cache inclui tenant e janela.
Selecionar período não dispara sync. A comparação executiva/Inteligência solicita
explicitamente outra janela de igual duração imediatamente anterior. Assim uma
análise de 90 dias pode ler até 180 dias para comparar, mas a coleta desta operação
continua limitada aos 90 dias solicitados: uma comparação anterior indisponível
permanece indisponível.

Publicações mensais e GA4 também consultam a janela selecionada e paginam os
dados persistidos. Métricas ausentes de snapshots Instagram aparecem como `—`;
insights lifetime de publicações não são transformados em métricas diárias.
Usuários GA4 somados por dia não são usuários únicos do período.
Receita/conversion value Google Ads permanece separada de receita do ecommerce.

## Coleta e persistência

| Provider | Mecanismo | Limite/semântica |
| --- | --- | --- |
| Meta Ads | Fila `meta_backfill` e worker existentes; fatias de sete dias | Conta/campanha/anúncio diários; conta selecionada; paginação existente; frequência preservada no raw de métricas existente. Alcance/frequência diários não são deduplicados de 90 dias. |
| Google Ads | Sync existente por fatias de sete dias, checkpoints `cron_job_runs` | Campanhas com fatos históricos, inclusive removidas; stream completo; conversões/valor atribuídos da fonte. |
| GA4 | Sync existente por fatias de sete dias, checkpoints `cron_job_runs` | Oito relatórios por fatia, incluindo relatório diário separado de compras/receitas; projeção após persistência completa. |
| Instagram | Enumeração paginada de publicações acessíveis, filtrada por timestamp local | Só metadados já suportados de conteúdo; não reconstitui snapshots de alcance, interações, seguidores ou Stories expirados. |

Google/GA4 usam locks existentes e checkpoint por tenant, conexão, recurso e
janela. `--resume` pula somente checkpoint explicitamente completo e projetado.
Persistência reutiliza chaves naturais; repetir não duplica fatos.
GA4 sinalizando amostragem, thresholding, truncamento, perda em `(other)` ou
restrição de métrica não recebe checkpoint completo. Paginação incompleta falha.
Dados válidos já persistidos não são apagados em falha; retomar pode regravar
idempotentemente a fatia. Não há nova tabela, migration, endpoint ou fila.

## Comandos futuros — NÃO executados

Executar apenas no ambiente operacional do backend, que já possui suas
credenciais; não copiar secrets para o Mac. Comandos abaixo partem da raiz do
repositório. Se o diretório operacional for `server`, usar `python run_jobs.py`.
Nenhuma opção aceita secret e não existe modo global.

```bash
python server/run_jobs.py provider-history --client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 --provider meta_ads --start-date 2026-07-08 --end-date 2026-10-05
python server/run_jobs.py provider-history --client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 --provider google_ads --start-date 2026-07-08 --end-date 2026-10-05 --resume
python server/run_jobs.py provider-history --client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 --provider ga4 --start-date 2026-07-08 --end-date 2026-10-05 --resume
python server/run_jobs.py provider-history --client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 --provider instagram_content --start-date 2026-07-08 --end-date 2026-10-05
```

Adicionar `--connection-id <UUID>` quando for preciso fixar uma conexão específica.
Para outros tenants, substituir explicitamente o UUID; não inferir IDs por nome.
Meta retorna `queued`, não coleta concluída. O worker existente
`python server/run_jobs.py ads-backfill-worker` processa a fila compartilhada;
não é um comando restrito a este tenant. O agendamento em `render.yaml` declara
uma execução a cada cinco minutos; operação efetiva em produção não foi verificada.
A rota existente `POST /api/ads/backfill` continua alternativa autenticada para
enfileirar Meta com `client_id`, `connection_id`, `since` e `until`.
Não foi criada rota operacional de Google/GA4/Instagram nesta mudança.
Render Free sem Shell exigirá ambiente de job operacional autorizado antes de
executar esses comandos; este documento não presume acesso disponível.

## Cobertura — somente leitura

```bash
python server/run_jobs.py provider-coverage --client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 --provider meta_ads --start-date 2026-07-08 --end-date 2026-10-05
python server/run_jobs.py provider-coverage --client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 --provider google_ads --start-date 2026-07-08 --end-date 2026-10-05
python server/run_jobs.py provider-coverage --client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 --provider ga4 --start-date 2026-07-08 --end-date 2026-10-05
python server/run_jobs.py provider-coverage --client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 --provider instagram --start-date 2026-07-08 --end-date 2026-10-05
python server/run_jobs.py provider-coverage --client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 --provider instagram_content --start-date 2026-07-08 --end-date 2026-10-05
```

Retorna dataset, janela, `coverage_start/end`, datas distintas, registros,
`last_sync_at`, `projection_success_at`, `completeness` e status operacional.
Só checkpoints completos Google/GA4 certificam a janela. Meta/Instagram
mantêm completude `unknown` nesta leitura: 90 datas não provam coleta completa.
Ausência de checkpoint mantém `last_sync_at=null`, sem inventar data usando
`updated_at`. Projeção é informada separadamente. Para Meta, complementar com
`GET /api/ads/backfill/{job_id}` e o resultado de suas fatias.
Status conservador: `sem dados`, `parcial`, `suficiente para 90 dias` somente
quando comprovado pelos checkpoints. Snapshots Instagram não reconstruíveis
são uma limitação do provider, não uma promessa de cobertura.

Cobertura real de Curavino, Roove, Origami, Ruah e Mugô: NÃO CONFIRMADA neste
ambiente. Schema implantado e disponibilidade das contas também exigem evidência
operacional. Origami/503 e Roove/502 permanecem incidentes sem diagnóstico.

## Custo e limites operacionais

90 dias geram 13 fatias. Estimativa de chamadas iniciais, não garantia de quota:

- Meta: até três relatórios canônicos por fatia (39), mais páginas, catálogo,
  probes existentes e retries. Uma fatia por worker; 13 ciclos de cinco minutos
  representam cerca de 65 minutos sem contenção ou retries.
- Google Ads: 13 search streams, além de OAuth, reprocessamentos e projeções.
- GA4: 104 chamadas iniciais (8 × 13), mais paginação, OAuth e retries.
- Instagram: enumera todas as publicações acessíveis, páginas de 100, até 200
  páginas; não presume ordenação suficiente para parar nos 90 dias. Upsert em
  lotes de 500 para o conteúdo selecionado.

Google/GA4: timeout de 240 segundos por fatia e 3300 segundos por operação;
lock operacional de 3600 segundos. Instagram: 1500 segundos. Limites excedidos
falham explicitamente. Quotas dependem da conta/propriedade e não foram medidas
em produção. Metadados GA4 são interpretados segundo a
[referência oficial](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/ResponseMetaData).

## Evidência local

`server/tests/test_provider_history_90_days.py` cobre ingestão diária de 90 dias,
reexecução, tenants, campanhas removidas, paginação, resume/locks/timeouts,
projeção, completude conservadora, conteúdo Instagram e limites da Inteligência.
`src/components/data/PeriodSelector.test.tsx` prova filtros reais 7/30/90,
cache por janela/tenant, personalizado inválido e paginação de 1101 campanhas.
`src/hooks/dashboard/useDashboardMonthlyContent.test.tsx` prova publicações
consultadas em 7/30/90, sem carregamento all-time.
Numeric grounding, tolerâncias e repair máximo de uma tentativa foram preservados.
