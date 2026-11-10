# Ajustes finais — base local 3c6cade

`git log -1` confirmou `3c6cade`. O workspace já tinha alterações não relacionadas, preservadas. A descrição do usuário informa que esse commit está em produção/teste; a versão publicada não foi consultada remotamente.

| Item | Causa / descoberta | Correção | Prova | GO local |
|---|---|---|---|---|
| META ADS | Sucesso da conexão era marcado antes da projeção; falha da RPC era ignorada. Consulta sem agregados usa `no_data/skipped` e preserva o último sucesso. Erro da fachada não identificava a fonte. | Aguarda e verifica projeção antes do sucesso; erro identifica Ads; status independente de Instagram; consulta vazia aparece separadamente; 429 explícito; logs de etapas sanitizados. | Regressões de projeção, status por fonte, erro Ads, no_data, tenant/período e rate limit; mutações detectadas. | GO |
| FBITS CUSTOMER | `usuario.nome/email/telefone*` → `normalize_customer` → `fbits_customers` → `_fbits_accumulators` → API já preserva os três campos. Não foi comprovada perda no código atual. | Persistência preservada; apresentação melhorada em Clientes. | `test_the_sync_persists_the_identity_alongside_the_orders`, casos de contato/nulos/privacidade em `test_fbits_customer_identity.py`, renderização FBITS existente. | GO |
| SHOPIFY CUSTOMER | `_build_customer_row` preserva `first_name/last_name/email/phone`; Customer 360 monta o nome a partir desses campos e o devolve com contato. Não foi comprovada perda no merge. | Persistência e matching preservados; apresentação melhorada em Clientes. | `test_a_recurring_customer_carries_name_email_and_phone` em `test_customers.py` e regressões da UI. | GO |
| CLIENTES | CTA só refazia leitura e era redundante. Ausência de nome mostrava `Cliente {external_id}`. A tabela desaparecia durante releitura mesmo com dados anteriores. | CTA removido; nome/email/telefone na mesma célula, antes dos dados comerciais; fallback email/telefone/“Não informado”; campos separados no drawer; tabela preservada em espera/falha. | `Customers.test.tsx`: ausência de CTA, contato, fallback, drawer, busca/paginação e revalidação com falha. Ecommerce mantém seu refresh e sua regressão passa. | GO |
| INTELLIGENCE | Não foi comprovado novo bug. Os handlers preservam análise durante geração/erro e separam releitura de geração. | Nenhuma alteração. | Regressões existentes de Intelligence e autorização; 267 testes backend focados passaram, além dos testes frontend e suíte completa. | GO |

## CONFIRMADO — Meta Ads

- Arquivo: `server/services/ads_sync.py`.
- Símbolo: `sync_ads_for_client_period`.
- Evidência: antes, `mark_connection_sync_success` antecedia `refresh_dashboard_read_model_safely`, cujo resultado não era verificado. Agora uma projeção `ok=false` interrompe com `META_ADS_PROJECTION_FAILED`; sucesso só é marcado depois da projeção.
- Conclusão: persistência isolada não é mais apresentada como sucesso de uma leitura que falhou. O teste `test_projection_failure_never_marks_success` reproduz essa fronteira e `test_freshness_is_projected_before_connection_success` comprova a ordem e tenant/período/provider usados na RPC.

- Arquivo: `server/services/provider_refresh.py`.
- Símbolo: `refresh_provider_data`.
- Evidência: a conexão paga persistida é resolvida por `client_id`, `platform=meta_ads`, `connection_type=paid`, `require_ad_account=True`; seu ID é passado ao sync com `persisted_only=True`. Instagram e Ads são aguardados por `asyncio.gather`. A resposta bem-sucedida Meta inclui apenas status sanitizados por fonte; exceções retornam o nome da fonte que falhou, sem sua mensagem crua.
- Conclusão: orgânico 200 não prova Ads e não encobre falha Ads. Ausência de conexão paga é registrada como `configured=False`; não foi inventada uma conexão nem conta. O período continua sendo o selecionado, normalizado pelo serviço existente.

- Arquivo: `src/pages/Dashboard.tsx`.
- Símbolo: `onRefresh` e cálculo de `paidFreshness`.
- Evidência: freshness de Ads lê a fonte `meta`, orgânico lê `instagram`. O novo status `no_data` é associado ao período consultado, sem fabricar timestamp de sucesso; o frontend continua sem reler após falha total, mantendo a última leitura. Uma consulta vazia anterior da conexão usa o rótulo “última consulta sem dados de anúncios”, sem atribuí-la a outro período.
- Conclusão: consulta vazia e ausência de sincronização têm apresentações distintas. Não foi feita migration para forçar freshness em ausência legítima de dados.

Pipeline Ads: conexão persistida/tenant → Graph → upserts e readback → projeção/freshness → sucesso da conexão → conclusão da fachada → releitura → UI. Consulta vazia segue `no_data`; duplicate/cooldown segue 429 com Retry-After. Rate limit da Graph é convertido em 429 sanitizado, com espera de 60 segundos quando o erro não fornece prazo.

Novos logs: `manual_refresh_start`, `connection_resolved`, `provider_start`, `provider_done`, `persist_done`, `freshness_updated`, `manual_refresh_done`, e código/status/reason em erros. `persist_done` informa contagem de linhas de conta no readback. `provider_done` fica depois da coleta, ou no ramo de consulta vazia. Os logs adicionados não contêm token, credencial, nome de cliente, contato ou payload Graph.

## CONFIRMADO — clientes e privacidade

- Arquivos: `server/services/fbits_connections.py`, `server/services/shopify_webhooks.py`, `server/services/customers.py`, `server/routes/customers.py`, `src/pages/Customers.tsx`.
- Símbolos: `normalize_customer`, `_build_customer_row`, `_fbits_accumulators`, `_shopify_accumulators`, `_identity`, `displayName`.
- Evidência: campos declarados são extraídos dos providers e retornados na apresentação; `_identity` recebe somente external_id/email/phone e mantém a prioridade atual. Nome não entra no matching. API/histórico não adicionaram CPF, endereço, pagamento ou raw payload.
- Conclusão: não houve justificativa para alterar persistência/merge. A ausência de contato na UI agora descreve os dados persistidos, sem afirmar que o provider não os oferece. FBITS depende da tabela `fbits_customers` existente; indisponibilidade dela já é registrada pelo serviço e não foi resolvida com migration nesta rodada.

## INTELLIGENCE preservada

`Intelligence.tsx`: última análise inicial vem do cache e da leitura persistida; `refreshData` não chama IA; `refreshAnalysis` mantém análise anterior e só substitui após resposta; erro não apaga análise. `server/routes/intelligence.py`: geração usa membership; `/ask` continua em `_mutation_context`, restrito a gestão. Nenhuma geração automática foi adicionada.

Testes existentes lidos: “Atualizar dados relê as fontes persistidas e NUNCA chama a IA”, “a análise anterior continua inteira enquanto a nova é gerada”, “falha da IA preserva a análise anterior e avisa discretamente”, “sucesso substitui a análise e avança o frescor da análise”. Todos passaram na suíte completa.

## SUSPEITA / produção

- Hipótese: falha de projeção ignorada, consulta sem dados ou conexão paga ausente explica o rótulo de Ads observado.
- Evidência parcial: esses caminhos existem no código, mas os logs fornecidos comprovam somente Instagram Graph 200; não há resposta Ads/RPC para essa tentativa.
- Falta: logs de Ads, conexão/conta efetivamente resolvida, persistência e fonte `meta` em produção.

Causa específica do incidente: **NÃO CONFIRMADO NO CÓDIGO.** Correspondência das correções com o ambiente publicado: **NÃO CONFIRMADO EM PRODUÇÃO.** Contatos efetivamente retornados pelos providers e presentes no banco remoto: **NÃO CONFIRMADO EM PRODUÇÃO.**

## Verificações executadas

Focadas primeiro: 103 frontend (Clientes/Intelligence/Meta/Ecommerce), 23 backend de refresh, 100 backend de clientes, 267 backend de Intelligence e 13 de Ads naquele momento; regressões adicionais entraram na suíte completa posterior.

- Frontend completo: **573 testes / 83 arquivos**, exit 0.
- Backend completo: **1306 testes**, exit 0.
- Lint, typecheck, build e `git diff --check`: exit 0.
- Mutações desta rodada: **6/6 detectadas**, em cópias temporárias: ignorar falha da projeção; ocultar fonte Ads; transformar consulta vazia em sucesso genérico; reintroduzir CTA Clientes; fabricar nome; confundir consulta vazia com ausência de sync.
- Runner: `server/tests/run_release_final_mutations.py`.

Diff da rodada: `/tmp/mugo-release-final.diff`. Alterações preexistentes foram excluídas desse artefato.

Sem commit, push, deploy, migration ou alteração de banco remoto. Nenhuma alteração em Google/Google Ads, OAuth, matching de clientes ou Intelligence. O tipo compartilhado de resposta ganhou um campo opcional consumido apenas pelo refresh Meta; os demais providers mantêm resposta/comportamento.
