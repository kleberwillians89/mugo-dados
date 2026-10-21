# Homologação local com Graphify — 20/10/2026

## Área e preservação

Trabalho em `/tmp/mugo-refresh-ui-x2q2vkal/checkout`, base `f32031c150027ae8e6d4ed38cceab16549317e16`. O checkout original `/Users/k/Desktop/mugo-dados` não recebeu alterações de código. Seu diff binário completo continua com SHA-256 `d0037e11bfe3bf5475c10d3c5efc3f17bf8c84aa832a4b49c2338c1b45bf901f`, igual ao início desta retomada. Os oito diffs paralelos foram comparados byte a byte com `/tmp/mugo-existing.patch`: idênticos. Index vazio nas duas áreas. Não houve staging, commit, push, deploy, migration, sincronização real ou alteração de dados remotos.

## Graphify

Confirmadas leitura do grafo original e execução de `/Users/k/.local/bin/graphify`. Consultados `query`, `explain`, `path` e `affected` para localizar consumidores de freshness, refresh, Inteligência e E-commerce; resultados conferidos no código. `ANALYSIS_SCHEMA` não foi resolvido como nó: conferido diretamente no arquivo. Atualização na área isolada com `graphify update . --no-cluster`: AST, sem LLM/API semântica. Grafo final: 7.454 nós / 19.865 relações. O extrator não cobre CSS e alguns arquivos sem símbolos; o grafo não substitui a leitura do código nem testes.

## 1. Ajustes anteriores — preservados, sem reimplementação

Os 13 arquivos pendentes anteriores mantêm os mesmos hashes da retomada (`../resume-state.json`). Indicador compacto em Meta/Google usa somente `last_successful_sync_at`, timezone `America/Sao_Paulo`, conserva sucesso anterior durante execução/parcial e mostra “Ainda não atualizado” quando ausente. Detalhes técnicos administrativos permanecem.

O botão usa trava síncrona local, autorização backend, estados/locks/cooldown existentes e GET de status limitado por tenant. Recupera execução no carregamento da página e não presume conclusão após erro HTTP. Sem retry automático de POST. Regressões em `DataHealthContext.test.tsx`, `useProviderRefresh.test.tsx`, páginas Meta/Google e `test_provider_refresh_status.py` passaram. Nenhum conector foi alterado.

## 2. Inteligência

### CONFIRMADO

- Arquivo: `server/services/intelligence.py`.
- Símbolos: `_assert_no_untrusted_numeric_text`, `_trusted_numbers`, `_call_analysis_with_numeric_repair`, `_call_provider`.
- Evidência: antes desta correção, a segunda tentativa reutilizava o schema de texto livre da primeira; o prompt orientava não inventar números, mas não impedia estruturalmente repetir a magnitude rejeitada. Duas respostas mockadas com 30 reproduzem a rejeição e persistência `failed`.
- Correção: exclusivamente no retry por `response.executive.main_change`, cópia do schema com `strict: true` e padrão qualitativo que não aceita dígitos, exceto o nome GA4. A primeira tentativa, demais campos, payload confiável, limite de duas chamadas e validador numérico permanecem. O schema global não é mutado. Versão do fingerprint atualizada para distinguir a política de repair.
- Não foi adicionada permissão especial para 30, removido valor da resposta ou transformado erro em sucesso. Resposta mockada que insiste em 30 continua falhando.

Cinco regressões novas em `server/tests/test_intelligence_numeric_repair.py` verificam retry restrito, rejeição repetida, métrica inicial sustentada, contexto legítimo de 30 dias e rejeição de 30 dias num período de 20 dias. Os exemplos de frases nos testes são sintéticos.

### NÃO CONFIRMADO

Origem semântica do 30 no incidente Curavino (01–20/10, Request ID `bba79761cf2c4d8f93d5f9b550986275`): **NÃO CONFIRMADO NO CÓDIGO.** O diagnóstico fornecido confirma a rejeição nas duas chamadas, mas não contém a frase original. Não foram consultados logs históricos remotos. O caminho de falha persiste o código do erro, não a resposta original rejeitada.

Compatibilidade do mecanismo fundamentada na documentação oficial de [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) e [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini). Testes locais usam mocks; aceitação real do schema e qualidade da resposta exigem homologação autorizada.

## 3. E-commerce e layout

`Ecommerce` tem ramos explícitos de carregamento, erro com retry, ausência de integração, escolha entre integrações e páginas FBITS/Shopify. Não foi identificado retorno silenciosamente vazio nesses ramos. `useActiveEcommerceProvider` valida o tenant da resposta e descarta requisições antigas; App remonta a página por tenant. Testes existentes cobrem troca de empresa, resposta atrasada, zero pedidos, permissões, período e preservação dos dados em falhas.

Acrescentadas somente duas regressões em `src/pages/Ecommerce.test.tsx`:

- `identificação pendente mostra carregamento sem chamar dados de nenhum provider`;
- `falha de leitura mostra erro e tentar novamente recupera sem sincronizar`.

Com Shopify e hook de refresh: 40 testes direcionados passaram. Nenhum defeito visual de produção foi comprovado. Empresa, período e tipo de tela vazia não foram identificados na evidência fornecida. Nenhuma alteração em FBITS/Shopify ou conectores.

Não foi possível fazer QA visual: CUA não disponibilizou navegador (`listBrowsers` vazio). Vite local iniciado para a tentativa foi encerrado. CSS possui regras responsivas, mas não se declara validação visual de todos os tamanhos. Pendentes capturas e respostas de API sanitizadas da ocorrência real.

## 4. Performance — investigação, sem refatoração

- `useProviderRefresh`: GET inicial recupera execução real; GET no clique verifica autorização/estado; GET após execução confirma conclusão. Enquanto ocupado/cooldown, polling de leitura a cada 5 s; status desconhecido, 15 s. Não executa POST repetido.
- Potencial leitura evitável: o `finally` de `run` chama `check()` mesmo quando a autorização inicial falha antes de executar a tarefa. Registrado por inspeção; não se afirma ganho medido. Mantido nesta rodada para não alterar o fluxo de bloqueio sem regressão específica.
- `DataHealthProvider`: compartilha GET em andamento e agrupa notificações em uma releitura; sem polling ocioso.
- `readOnce`: deduplica leituras simultâneas pela chave, remove promessa no finally. Duas chamadas de hooks não demonstram, por si só, duas chamadas HTTP.
- E-commerce: teste comprova uma leitura de conexões; detalhes são demandados por seção, sem chamar o provider não selecionado.
- IA: os tempos fornecidos somam aproximadamente 25,04 s nas duas chamadas do modelo, dentro de 32,06 s totais. Não há evidência local para atribuir o restante a uma dependência específica. Não foram medidos tempos reais de produção nesta rodada.

## Validação executada no candidato

- Backend completo: `APP_ENV=production PYTHONPATH=server:server/tests /tmp/mugo-memory-venv/bin/python -m unittest discover -s server/tests -p 'test_*.py'`: **1.554 passaram**.
- Inteligência direcionada (numeric repair, grounding, vocabulário, partial today, compatibilidade temporal): **179 passaram**.
- Frontend completo: `npm run test:frontend`: **675 passaram, 98 arquivos**.
- E-commerce / Shopify / hook refresh direcionados: **40 passaram**.
- `npm run lint`, `npm run typecheck`, `npm run build`: passaram.
- `APP_ENV=production /tmp/mugo-memory-venv/bin/python -m compileall -q server`: passou.
- `git diff --check`: passou.

Logs locais ficam na pasta pai: `backend-homologation.log`, `ai-targeted.log`, `commerce-targeted.log`, `homologation-frontend.log`, `homologation-lint.log`, `homologation-typecheck.log`, `homologation-build.log`, `graphify-update-final.log`. Warnings de ambiente Node/localStorage e tempos de plugins Vite não impediram execução.

## Arquivos do candidato (17)

13 anteriores preservados:

1. `server/routes/integrations.py`
2. `server/services/provider_refresh_status.py`
3. `server/tests/test_provider_refresh_status.py`
4. `src/App.tsx`
5. `src/app/DataHealthContext.test.tsx`
6. `src/app/api.ts`
7. `src/components/data/DataFreshness.tsx`
8. `src/hooks/useProviderRefresh.ts`
9. `src/hooks/useProviderRefresh.test.tsx`
10. `src/pages/Dashboard.channelReport.test.tsx`
11. `src/pages/Dashboard.tsx`
12. `src/pages/GoogleAnalytics.refresh.test.tsx`
13. `src/pages/GoogleAnalytics.tsx`

Nesta retomada:

14. `server/services/intelligence.py`
15. `server/tests/test_intelligence_numeric_repair.py`
16. `src/pages/Ecommerce.test.tsx`
17. `docs/homologation-graphify-audit.md`

`graphify-out/` é artefato local de navegação, fora desta lista de código. Nenhum staging realizado.

## Pendências e veredito

Apto à próxima homologação controlada, sem alegar incidente resolvido. Antes da publicação: validar repair com o modelo configurado, primeira tentativa com métricas sustentadas, recarga durante refresh/timeout/cooldown, viewer 403, troca de tenant/período, últimos sucessos em São Paulo e estados E-commerce nos tenants afetados. QA visual desktop/mobile permanece pendente. Origem histórica da frase 30 permanece inconclusiva. Commit/push/deploy não executados nem autorizados nesta rodada.
