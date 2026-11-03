# Integração Meta: velocidade do primeiro carregamento

## Linha de base (produção, 90 dias, `cron_job_runs`)

| Job | Execuções | Mediana | Máx. | Não-sucesso | Motivo |
|---|---|---|---|---|---|
| `meta_ads_initial_sync` | 8 | 3,2 s | 31,9 s | 7 | conta sem gasto no período (`skipped`, não é erro) |
| `meta_ads_manual_account_sync` | 5 | 3,1 s | 3,5 s | 5 | 3 sem gasto, 2 clique duplicado bloqueado |
| `history_backfill_block` | 126 | 1,5 s | 33,0 s | 52 | Meta: fila ocupada (corrigido no PR #112); Google/GA4: código real passa a ser gravado; Shopify: falta `read_all_orders` |

A coleta em si é rápida. O tempo até o primeiro número vinha de **quanto a requisição esperava** antes de liberar a tela.

## Caminho crítico antes

OAuth → descoberta completa dentro do callback → ativação do Instagram com **sync completo** (40 posts, comentários e miniaturas) dentro da requisição → Meta Ads com **30 dias completos** (conta, campanhas, anúncios e impulsionados) dentro da requisição.

## O que mudou

1. **Descoberta** (`meta_oauth.discover_assets`)
   - Sem a segunda chamada por Página: `/me/accounts` já traz nome e Instagram.
   - `/me`, Páginas, contas de anúncio, permissões e Businesses saem em paralelo.
   - As leituras do diagnóstico (permissões e `debug_token`) também saem em paralelo, sem somar tempo.
2. **Instagram:** a ativação espera só perfil, KPIs e os 12 posts mais recentes, sem miniaturas. O sync completo roda logo depois da resposta (`meta_progressive`).
3. **Meta Ads:** ao salvar a conta, a requisição espera 7 dias. Depois, em segundo plano, roda 30 dias completos e o restante dos 90 dias entra na fila durável.
4. **Tela:** "Sincronizando histórico…" com o último sucesso, além de "sem anúncios no período", "reconectar" e "parcial", que já existiam. Enquanto sincroniza, o status é relido a cada 15 s (no máximo cerca de 20 min). Quando termina, o dashboard relê os dados sozinho.

Nada mudou em permissões e escopos, na validação de tenant, nos tokens (continuam só no backend), nos locks ou no registro de jobs.

## Antes e depois

**Descoberta**, medida com `server/scripts/bench_meta_discovery.py` (código real, Graph simulada a 250 ms por chamada):

| Cenário | Chamadas antes → depois | Em fila (equivalente) antes → depois | Tempo a 250 ms antes → depois |
|---|---|---|---|
| Cliente pequeno: 5 Páginas, 1 BM, 3 contas | 17 → 12 | 13 → 3 | 3,3 s → 0,75 s |
| Conta da agência: 40 Páginas, 3 BMs, 20 contas | 64 → 24 | 51 → 6 | 12,8 s → 1,5 s |

Os ativos encontrados são os mesmos nos dois casos. O tempo real depende da latência real da Meta; o que o medidor garante é a forma (número de chamadas e chamadas em fila).

**Ativação.** Estes números são derivados do código, não medidos:

| | Antes | Depois |
|---|---|---|
| Instagram na requisição | 40 posts × (métricas + comentários) + 40 miniaturas + ~5 fixas | 12 posts × (métricas + comentários) + ~5 fixas |
| Meta Ads na requisição | 30 dias × 4 níveis | 7 dias × 4 níveis |

## Medir em produção depois do deploy

```sql
select job_name, count(*),
       round(percentile_cont(0.5) within group (order by extract(epoch from finished_at - started_at))::numeric, 1) as mediana_s,
       count(*) filter (where status = 'error') as erros
from cron_job_runs
where job_name in ('meta_ads_initial_sync', 'meta_ads_history_30d') and started_at > now() - interval '30 days'
group by 1;
```

Nos logs do Render:
- **Descoberta:** diferença entre `[meta_oauth] stage=state_validated` e `stage=authorization_saved`.
- **Instagram:** `[meta-organic-real] stage=sync_start` → `stage=complete` (primeiro KPI).
- **Histórico em segundo plano:** `[meta_progressive] stage=start` → `stage=done`.

## Limites conhecidos

- O segundo plano roda no processo web. Se o Render reiniciar no meio, os syncs recorrentes (`organic-sync` 4 vezes ao dia, `ads-sync-hourly`) e a fila durável completam depois.
- Aprovação de permissões (App Review) é outro assunto: não muda com isso.
