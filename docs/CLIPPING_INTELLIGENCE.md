# Clipping Intelligence

Evolução do clipping que já existia (`studio_clipping`), em **Operação → Clipping**. Não é um módulo paralelo.

## Auditoria

| Item | Situação encontrada |
|---|---|
| Clipping no Dados | Já existia: Google Notícias por termo de marca e concorrente, IA com sentimento e resumo de 1 linha, por cliente (`studio_clipping_settings`, `studio_clippings`). |
| Tenants e permissões | `require_client_read` e `require_client_role` resolvem a empresa no backend. O cliente lê o próprio clipping; configurar, buscar, relatório e exportação são da agência. |
| IA | `studio_llm.llm_json` (OpenAI, saída validada por schema). |
| Notificações | Central de Automações (PR #74): fila idempotente, envio só com template aprovado na Meta. |
| CRM | O motor de notícias está em `newsletterCore.js` (funções puras) e na Edge Function `newsletter`. Não existe API do CRM para coleta de notícias por cliente. |

## Reaproveitamento do CRM

O CRM é JavaScript (Deno) e o Dados é Python. Não existe endpoint de notícias no CRM, e criar um exigiria mexer na newsletter em produção. Por isso as **regras puras** foram portadas para `server/services/news_engine.py`, com a mesma lógica:

| CRM (intacto) | Dados |
|---|---|
| `newsletterCore.js` `parseFeed` (RSS 2.0 + Atom, tolera feed truncado) | `parse_feed` |
| `bestExcerpt` + limpeza de rodapé de WordPress | `best_excerpt` |
| `extractArticleText` (og:description + parágrafos, sem ruído) | `extract_article_text` |
| `balanceCandidates` (um veículo não domina o lote) | `balance_by_source` |
| `validateCuration` (a IA só cita o que foi coletado) | `evidence_in` e a validação de URLs do relatório |
| `temporalIntelligence.js` `temporalPriority` | `recency_priority` |

A newsletter do CRM não foi alterada. Os testes de `test_clipping_intelligence.py` fixam o comportamento: se mudar no CRM, ajustar aqui também.

**Ficou de fora:** `causalAnalysisEngine.js` e o `prospecting`, que são de outros domínios (vendas e leads).

Fontes ficam atrás de uma interface (`GoogleNewsProvider`, `FeedProvider` e `GdeltProvider`). O GDELT está preparado e **desligado**; nenhum serviço pago foi ativado.

## Dados (migração 000063, aditiva)

- `news_articles`: catálogo **público e compartilhado** (URL, título, veículo, data, trecho, texto extraído). O texto é coletado uma vez para todas as empresas, o que funciona como cache.
- `studio_clipping_settings`: radar completo por cliente. Marca e variações, concorrentes, pessoas e porta-vozes, palavras-chave, temas, fontes RSS próprias, região, critérios de relevância, relevância mínima e limite diário de IA.
- `studio_clippings`: análise **por cliente**. Relevância de 0 a 100, sentimento (positivo, negativo, neutro, misto), criticidade, tema, entidades, oportunidades, riscos, justificativa, evidências e estado do alerta.
- `clipping_ai_usage`: matérias analisadas por cliente e por dia.
- `automation_definitions.clipping_critico`: alerta interno, que fica bloqueado até existir o template `mugo_alerta_clipping` aprovado na Meta.

Validada em Postgres 16 local: aplica e reaplica, a mesma matéria fica com análises diferentes por cliente e o catálogo não duplica.

## Fluxo

Encontrar (Google Notícias por termo + RSS próprios filtrados pelos termos) → deduplicar (URL e manchete normalizada) → equilibrar por veículo → catálogo (texto extraído uma vez) → análise contextual por cliente (lote de 12, dentro do limite diário) → painel → relatórios → alerta à equipe.

- **Sem inventar:** evidência que não está no título ou no texto é descartada. Sem evidência, a relevância fica limitada a 40 e a criticidade vai para baixa. Relatório só aceita URL de matéria coletada. Sem IA, a matéria entra sem análise.
- **Contextual:** o prompt leva o radar daquele cliente. A mesma matéria tem uma linha por cliente, cada uma com a sua análise.
- **Revisão humana:** matéria crítica (crítica, ou alta e negativa, com relevância 60+) só aparece para o cliente depois que a equipe a marca como lida. O alerta automático vai **só** para a equipe Mugô.
- **Custos:** limite diário de IA por cliente, intervalo mínimo de 10 min no "Atualizar agora", job diário (`studio-clipping`, já existente) e texto extraído com cache no catálogo.

## Endpoints (prefixo `/api/clients/{client_id}/studio`)

| Rota | Quem |
|---|---|
| `GET /clipping?q=&kind=&sentiment=&theme=&min_relevance=&criticality=` | membro (cliente: só o relevante e revisado, sem justificativa e evidências internas) |
| `GET /clipping/insights?days=` | membro (mesmo filtro) |
| `PUT /clipping/settings` (radar) | agência |
| `POST /clipping/report` `{period: diario, semanal ou mensal; focus: cobertura, concorrentes, setor ou riscos}` | agência |
| `GET /clipping/export?days=` (CSV) | agência |

## Pendências

1. **Coleta real não homologada daqui:** a rede desta sessão bloqueia `news.google.com`. Homologar no Render: configurar o radar de um cliente, clicar em "Atualizar agora" e conferir as matérias, a deduplicação e a análise.
2. Aplicar a migração 000063 no Supabase (depois da 000062 do PR #74).
3. Criar e aprovar na Meta o template `mugo_alerta_clipping` (variáveis: nome, marca, título, criticidade) e cadastrar a equipe com "alertas de campanha" na Central de Automações.
4. Opcional, no futuro: um endpoint de notícias no CRM, se quiserem uma única coleta para os dois sistemas; e o GDELT (`GdeltProvider`), quando for aprovado.
