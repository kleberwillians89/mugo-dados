# Fase 1 — estabilização local do Mugô Dados

Data: 20/10/2026. Escopo: implementação e validação locais; nenhuma publicação.

## A. Mobile e responsividade

CONFIRMADO — `src/styles/design-system.css`: a grade de KPIs móvel tinha três colunas fixas. Foi substituída por grade fluida com mínimo de 140 px limitado ao espaço disponível. Valores e cabeçalhos podem quebrar linha; controles de período se redistribuem. `shell.css` limita o seletor de empresa à viewport. `App.css` limita o contêiner externo das tabelas, preservando rolagem interna das tabelas largas. `shopify-report.css` deixa de mascarar overflow da página por `overflow-x: clip`.

`src/styles/intelligence.css` usa leitura vertical no mobile. `Customers.tsx` permite foco na região de tabela; o CSS indica rolagem localizada. Menu e modal contêm Tab/Shift+Tab e restauram foco/scroll; mudança para desktop fecha a gaveta. O callback atualizado do modal não reinicia o foco durante edição. São correções confirmadas no código e em testes DOM; ausência de overflow visual nos oito breakpoints ainda não foi comprovada.

## B. Design system

Reutilizados tokens e componentes existentes: `KpiFigure`, `HeroFigure`, `KpiCard`, `ShopifyKpiCard`, `AppNavigation` e `Modal`. As alterações tratam limites intrínsecos, quebra de texto, ações e foco. Não houve troca de identidade, biblioteca visual ou arquitetura. Não foi realizada certificação WCAG ou medição visual de contraste.

## C. Glossário

`src/app/metricGlossary.ts` centraliza definições tipadas, fórmulas, unidades, fontes e ressalvas. `MetricHelp` usa portal, foco/hover, toque, Escape, fechamento externo e posicionamento limitado à viewport; estilos respeitam os tokens existentes. O ícone não aciona a seleção do KPI.

Termos obrigatórios foram registrados. Integração nos indicadores compartilhados, mídia paga, GA4, Clientes, E-commerce e Inteligência. Termo desconhecido não recebe definição presumida. Retorno combinado da loja, ROAS atribuído e conversões GA4 possuem explicações distintas; fórmulas de KPI não foram alteradas. Não se afirma cobertura automática de todo rótulo dinâmico possível.

## D. Atualização dos dados

`useProviderRefresh` mantém trava síncrona antes do rerender, autorização prévia e consulta ao estado real do servidor. Reutiliza leases/cooldown existentes e o orquestrador existente. A rota de leitura de status passa a aceitar também Shopify/FBITS, sem modificar os conectores; consulta limitada a 101 leases, filtrada por tenant e prefixos da operação, com falha segura caso exceda 100.

Estados: verificação, execução, cooldown, pronto, acesso negado e resultado da solicitação. Falha HTTP não confirma término do backend. Remontagem, foco e sinal entre abas consultam o servidor. BroadcastChannel transmite apenas escopo de empresa/provider; é informativo, não autoridade nem cache de dados. Outras sessões são observadas por polling: 5 s bloqueado, 15 s após leitura indisponível e 30 s pronto/visível. Não há repetição automática de POST.

`ProviderRefreshNotice` usa evidência persistida de parcial da mesma plataforma, identifica que pertence à última coleta registrada e não apresenta parcial como sucesso completo. Data/hora compacta usa exclusivamente `last_successful_sync_at`, em America/Sao_Paulo; ausência é “Ainda não atualizado”. O fallback ambíguo `last_sync_at` deixou de ser usado para certificar sucesso no E-commerce.

Não foi criado mecanismo de exactly-once ou novo sistema de jobs. Expiração de lease após falha de processo e comportamento entre processos reais continuam sujeitos à homologação; testes mockados não demonstram execução distribuída em produção.

## E. Inteligência e validação

CONFIRMADO — `server/services/intelligence.py`, `_generate_with_provider`: após o reparo numérico, `_validate_analysis_grounding` rejeitava toda a operação por uma seção opcional temporalmente incompatível. O diagnóstico fornecido da Roove informa token 50 reparado e depois incompatibilidade entre commerce sem cobertura e mídia com cobertura. A frase histórica completa não foi disponibilizada; os logs remotos não foram consultados nesta rodada. Seu conteúdo original é NÃO CONFIRMADO NO CÓDIGO.

Correção: a política enviada ao modelo explicita métricas com cobertura insuficiente. Nenhum dado disponível evita a chamada paga e gera erro explícito de insuficiência. Após rejeição temporal específica, `_recover_temporal_sections` descarta comparações opcionais incompatíveis, exige conclusão útil restante, verifica procedência e substitui integralmente resumo e ações que poderiam repetir texto rejeitado. O resultado inteiro passa novamente pelos validadores numérico e de grounding. IDs inexistentes, procedência incorreta, números inventados e resultado sem seção útil continuam recusados.

A recuperação é determinística, sem terceira chamada ao modelo; o limite existente de geração + reparo numérico permanece em duas. O registro mantém o contrato `status=completed` para geração concluída, com `data_quality.status=partial` e mensagem explícita de análise parcial. Interface identifica a limitação. `ANALYSIS_VERSION` foi incrementada para não reutilizar análises antigas como resultado da nova política. Nenhum schema/enum/migration foi alterado.

`server/routes/intelligence.py` distingue mensagens de insuficiência, cobertura incompatível, validação e timeout; mantém o contrato HTTP de erro. A proteção numérica não foi desativada nem recebeu whitelist de 30 ou 50. Histórico não foi apagado. Recuperação automática da última análise boa após recarregar uma página cujo registro mais recente falhou não foi ampliada nesta rodada.

Regressões em `server/tests/test_intelligence_temporal_recovery.py`:

- `test_numeric_50_repair_then_temporal_optional_section_recovers`: sequência sanitizada determinística, no máximo duas chamadas mockadas, parcial revalidado e persistido.
- `test_no_useful_section_still_fails_and_persists_error`: não produz parcial falso.
- `test_recovery_does_not_hide_unknown_source_or_publish_rejected_executive`: fonte inexistente continua recusada.
- `test_timeout_is_classified_without_inventing_a_partial_result`: timeout persistido como erro.
- `test_recovery_is_not_mutation_and_keeps_validators_active`: entrada preservada e original rejeitado.
- `test_no_data_avoids_model_and_persists_explicit_error`: nenhuma chamada ao modelo sem métricas disponíveis.
- `test_partial_recovery_does_not_relabel_a_metric_as_another_known_source`: procedência incorreta continua recusada.

O teste temporal preexistente passou a conferir recuperação parcial, mantendo uma asserção de rejeição do conteúdo original. A fixture reproduz a estrutura do incidente informado, não uma resposta histórica recuperada.

## F. Contexto de negócio

Auditoria de `server/services/business_context.py`: contexto existente filtrado por tenant, permissões e limite de texto preservados. Não foram criados campos de banco. `BusinessContextPanel` apenas esclarece onde registrar referência de ticket, prioridades e restrições nos campos existentes. Briefing ausente continua não bloqueando análise básica; nenhuma informação ausente é preenchida artificialmente.

## G. Performance

Medição local de requisições mockadas, comparando o hook da referência 8bc88d73d38f36cb6f988b598445a9b1bf85054c com o atual, sob as mesmas regressões:

| Cenário | Antes | Depois |
| --- | ---: | ---: |
| Montagem + tentativa recusada: GETs de status totais | 3 | 2 |
| Três eventos de foco simultâneos durante leitura | 3 | 1 |

As duas regressões falham na referência e passam no candidato. Leitura em voo é compartilhada somente pela instância e geração do hook; não existe cache global sensível. O finally não repete consulta quando o pré-check já recusou a operação. Polling periódico acrescenta leitura limitada para observar outras sessões; essa é uma troca explícita, não promessa de redução global de tráfego.

Logs: `/tmp/mugo-phase1-01shb_p9/performance-before.log` e `performance-after.log`. Não houve medição de latência/RSS em produção. As amostras de 3,56 s/3,37 s/3,11 s/2,42 s/2,10 s fornecidas não foram reexecutadas nem convertidas em médias. Não houve remoção de checagens de autorização.

## H. E-commerce

Shopify/FBITS reutilizam os estados existentes de carregamento, erro, sem integração e sem dados, o mesmo orquestrador e releitura de snapshots persistidos. Últimos dados válidos permanecem durante execução/falha no fluxo existente. Novos controles de status não alteram pedidos, webhooks, HMAC, OAuth, regras de receita ou conectores. O glossário distingue vendas da loja de atribuição de mídia. A alegação histórica de “tela vazia” não pôde ser atribuída a empresa/período específicos; não foi declarada resolvida por suposição.

## I. Testes e QA

Validação final executada:

| Verificação | Resultado |
| --- | --- |
| Backend completo, unittest, APP_ENV=production, ambiente local de testes | 1.570 aprovados |
| Frontend completo, npm run test:frontend | 695 aprovados, 103 arquivos |
| npm run lint | aprovado |
| npm run typecheck | aprovado |
| npm run build | aprovado |
| Typecheck estrito específico do harness | aprovado |
| Build separado design-review.html | aprovado |
| Python compileall de server | aprovado |
| git diff --check | aprovado |

A primeira execução frontend desta conclusão encontrou falha no teste novo de foco do modal. O seletor foi corrigido para preservar ordem DOM; regressões direcionadas e a suíte completa foram reexecutadas com sucesso. Nenhum teste foi desativado. Permanecem avisos de ferramentas: Node local 26 versus engine 22 declarada, localStorage experimental/JSDOM, depreciação de module.register e aviso de chunk grande no build do harness. Não foram tratados como defeitos funcionais nem ocultados.

Graphify foi consultado e atualizado localmente por `graphify update . --no-cluster`: 7.599 nós, 20.270 arestas, sem LLM. Dependências confirmadas no código; extração não modela CSS e alguns arquivos sem símbolos. Artefatos em graphify-out são auxiliares locais, fora do manifesto de produto.

Computer Use não ofereceu navegador (`apps: [], browsers: []`). Nenhuma captura visual foi produzida. Testes DOM e geometria simulada não substituem inspeção nos oito breakpoints. Harness, URLs e roteiro em `docs/phase1-qa.md`.

## J. Pendências, riscos e parecer

**GO para revisão técnica e início do QA visual local. NO-GO para declarar a Fase 1 totalmente homologada ou publicar sem o QA visual pendente e autorização posterior.**

Pendências reais: oito larguras no navegador, screenshots, ausência de overflow global, contraste, gráficos/tabelas reais, duas sessões reais, transições de jobs/cooldown e confirmação da IA temporal com dados autorizados. Sem executar novas análises pagas/sincronizações nesta rodada. O caso Curavino/token 30 sem frase original também não tem causa histórica comprovada.

Estado Git: main, HEAD 35e138b8ed1b67cba77606a4724c5e66458e6348 inalterado. O checkout já continha a integração anterior em diffs; a referência publicada informada é 8bc88d73d38f36cb6f988b598445a9b1bf85054c. Não confundir HEAD antigo do checkout com novo commit de release. Index vazio; nenhum staging/commit/push/deploy.

Oito diffs paralelos preservados byte a byte contra o backup desta fase: `.gitignore`, `server/routes/google.py`, `server/routes/meta_legacy.py`, `server/services/invitations.py`, `server/tests/test_meta_onboarding_authorization.py`, `server/tests/test_platform_admin.py`, `src/components/shell/AppNavigation.test.tsx`, `src/design-review/ReviewApp.tsx`. SHA-256 do patch conjunto: dab4eac26e9f48a5db1d64c0f1752b78e541700a395304664149fe06d7cebcab. Arquivos anteriores preservados; manifesto exato e hashes em `docs/phase1-files.json` (46 arquivos de código/testes/estilos e três documentos desta fase). A lista não autoriza staging de diffs anteriores presentes nos mesmos caminhos.

Recuperação local: backup `/tmp/mugo-phase1-01shb_p9` contém patch e hashes anteriores. Reverter somente hunks desta fase após comparação; nunca resetar o checkout sujo. Para eventual publicação futura, isolar candidato e comparar à referência 8bc; não publicar todo o diff contra HEAD automaticamente. Rollback de produção deve usar a última release efetivamente homologada, com nova autorização; não há migration desta fase a reverter.

## Adendo — homologação final local

A pendência de navegador desta entrega inicial foi superada via Chromium/Playwright. Consulte `docs/phase1-final-homologation.md` para o estado atual: 72 combinações tela/largura, 19 cenários de interação e 64 verificações de glossário; 1.571 testes backend e 697 frontend. O adendo substitui o NO-GO motivado exclusivamente por ausência de QA visual. O histórico acima descreve a implementação anterior e suas contagens de arquivos/testes. O manifesto atual inclui os ajustes comprovados na homologação. Não houve publicação.
