# Homologação final local — Fase 1

20/10/2026. Chromium real, headless, controlado por Playwright instalado no runtime local. A ferramenta Computer Use não ofereceu superfícies; o navegador foi executado localmente com permissão para iniciar processos. Não houve uso de sessão real, provider, Supabase remoto ou IA paga.

**Parecer: GO técnico para preparar uma publicação controlada, após autorização. Homologação local concluída no Chromium com fixtures. Isso não confirma publicação nem substitui o smoke de leitura pós-deploy.**

## Acesso local

Frontend mantido em `http://127.0.0.1:5173/design-review.html`. Backend não iniciado. O processo de revisão usa URL Supabase fictícia local e chave placeholder somente no comando de inicialização, sem alterar arquivos de ambiente. O harness bloqueia fetch externo e os contextos Playwright também abortam rede fora de localhost. Não usar a raiz do app como teste de login real com essa configuração fictícia.

## Matriz efetivamente executada

Viewport CSS: 320×844, 360×844, 375×844, 390×844, 430×844, 768×900, 1024×900 e 1440×900. Capturas integrais têm altura maior que a viewport quando a página rola.

Em cada largura: Meta/Dashboard (inclui seção Instagram), Google Ads, GA4, Inteligência, E-commerce FBITS, E-commerce Shopify, Conexões/Integrações, glossário e Saúde dos Dados. Não existe uma rota separada de Dashboard/Instagram no harness: são as composições reais da tela Meta. Saúde é o componente real `DataHealthSummary`, montado com seu provider real e dados fictícios em `?tela=saude`.

Resultado consolidado: **72/72 combinações sem overflow horizontal global e sem exceção de renderização**. Critério medido: `document.documentElement.scrollWidth <= document.documentElement.clientWidth`. Seções lazy foram percorridas antes da captura. Tabelas e histórico largos continuam rolando dentro do componente. As capturas foram produzidas por navegador; não são renders de JSDOM.

Além da medição, foram inspecionadas capturas representativas de mobile, tablet e desktop, incluindo conteúdo de Meta/Instagram, GA4, Google Ads, IA, FBITS, Shopify, Conexões, Saúde, menus, tooltips e estados de atualização. Isso não é certificação pixel a pixel nem validação em aparelho físico/Safari.

Evidência estruturada: `/tmp/mugo-phase1-visual-final/matrix-final.json`. O primeiro lote de Saúde usava a tela Meta e não montava o resumo: foi descartado da matriz final e substituído pelas oito capturas do componente correto, registradas em `health-matrix.json`.

## Defeitos confirmados e correções mínimas

| Severidade | Evidência | Correção |
| --- | --- | --- |
| Alta | `Dashboard.performRefresh` capturava erro e resolvia a tarefa; o hook publicava sucesso apesar de falha de provider/releitura. Duas asserções de regressão falharam antes da correção. | Propagar a falha ao controlador, manter tratamento amigável externo e leitura anterior. `Dashboard.tsx` e regressões de página. |
| Alta | `PeriodTransition` retinha React nodes antigos durante revalidação do mesmo período: controles e erro podiam ficar congelados. Regressão reproduziu botão antigo em vez de botão bloqueado/erro atual. | Reter composição apenas durante troca de período. Atualização no mesmo período usa filhos atuais. Testes mantêm retenção entre períodos e isolamento de tenant. |
| Média | Meses se sobrepunham no histórico Shopify em 320 px. | Largura mínima por barra, rolagem local já existente preservada, foco por teclado e indicação de deslize no mobile. Nenhuma métrica alterada. |
| Harness | Chave antiga `read-model-ytd-v2`, ausência de leitura mockada do read model, GA4 sem fixture de relatório, catálogo FBITS divergente do canônico e stories sem fixture. | Chave atual, respostas locais limitadas ao contrato, FBITS fictício coerente, relatório GA4 e stories fictícios, bloqueio de rede externa. Não alterar regras do produto para adaptar o harness. |
| Harness | Saúde dos Dados não era montada. | Entrada local `tela=saude` com componente/provider reais. Nenhuma rota de produção nova. |

Arquivos de código/testes alterados nesta rodada (12):

- `server/tests/test_intelligence_temporal_recovery.py`
- `src/components/data/PeriodTransition.tsx`
- `src/components/data/PeriodTransition.test.tsx`
- `src/components/shopify/ShopifySalesHistory.tsx`
- `src/design-review/main.tsx`
- `src/design-review/fixtures.ts`
- `src/design-review/diagnosticMocks.ts`
- `src/design-review/diagnosticMocks.test.ts`
- `src/design-review/ReviewScreen.tsx`
- `src/pages/Dashboard.tsx`
- `src/pages/Dashboard.channelReport.test.tsx`
- `src/styles/shopify-report.css`

Documentação: este relatório, `phase1-qa.md`, adendo em `phase1-stabilization-audit.md` e manifesto atualizado `phase1-files.json`. O manifesto da Fase 1 inteira contém 57 caminhos (53 de código/testes/estilos e quatro documentos) e não equivale ao diff exclusivo desta rodada.

## Atualizar Dados e permissões

**19 cenários de interação aprovados** (`interactions.json`): menu mobile/Escape/foco; tooltips nos dois extremos de largura; execução e cooldown preservados ao recarregar; viewer sem botão Meta nem link de integrações; falha e sucesso simulados; um único POST lógico mesmo com cliques adicionais; dados anteriores preservados; filtro de sete dias; carregamento secundário do Instagram; recuperação parcial da IA; IA carregando/erro/vazio/parcial; FBITS erro/sem vendas/pendente/carregando.

Disponível, verificação de acesso, processando, cooldown, sucesso e erro foram exercitados com o componente/controlador reais e transporte fictício. O sucesso foi testado com POST mockado e releitura persistida mockada completa; o erro preserva os cards e não mostra “Seus dados foram atualizados.”. Running/cooldown são fixtures estáticas e não certificam scheduler ou lock distribuído real. Os testes backend existentes de autorização/tenant continuam na suíte completa; nenhuma permissão foi alterada nesta rodada.

Cinco verificações adicionais aprovadas (`graph-navigation.json`): troca de métrica e tooltip do gráfico em 390/1440 px, rótulos de meses sem sobreposição nas duas larguras e troca Roove/Shopify para Curavino/FBITS no desktop. As capturas de detalhe permitem ler os rótulos corrigidos.

## Glossário

**32 termos × duas larguras = 64 verificações aprovadas**, usando toque em 320 px e foco em 1440 px. Inclui CPC, CTR, ROAS, CTA, sessões, eventos e demais definições registradas. Tooltip dentro dos limites horizontal/vertical; fechamento por Escape aguardado após atualização do React. Seis termos principais também foram exercitados por clique na suíte de interações e possuem capturas próprias.

Uma asserção inicial consultava imediatamente a contagem do tooltip após Escape e falhou antes do commit do React; foi substituída por espera de fechamento. Uma tentativa de percorrer todos os termos por mouse em viewport touch ativou hover acidental durante rolagem; a execução final usa toque/foco apropriados. Nenhuma dessas tentativas foi contabilizada como aprovação sem repetição.

## Inteligência — Roove

`test_http_route_serializes_recovered_partial_as_200_after_numeric_repair`, em `server/tests/test_intelligence_temporal_recovery.py`, usa a rota FastAPI real via ASGI, geração/validação reais e IO mockado. Snapshot e membership são fixtures. Reproduz número 50 rejeitado, reparo numérico aprovado e seção opcional temporalmente incompatível. Resultado: **HTTP 200**, geração `completed`, `data_quality.status=partial`, duas chamadas de modelo mockadas, uma persistência mockada e comparação rejeitada ausente. Não foi forçado HTTP 200 no código de produção.

A saída revalidada foi usada no transporte fictício do browser para testar a página real no período **01/10/2026–20/10/2026**. Campos de apresentação normalmente adicionados pelo calculador de snapshot (rótulos, cliente, datas e metadados) foram completados no fixture visual; números e texto recuperados não foram alterados. Captura `roove-recuperacao-parcial-390.png`: identificação de análise parcial, métrica indisponível explicitamente marcada, texto rejeitado ausente e botão fora de loading. Não se trata de consulta ou replay de uma resposta histórica original.

Uma primeira tentativa usava fixture de teste de serviço sem os rótulos obrigatórios do contrato visual e produziu tela branca. A fixture foi completada e a execução repetida. Não houve flexibilização de validadores nem alteração de contrato para aceitar essa fixture incompleta.

## Validação final

- Backend completo: **1.571 testes aprovados** (antes: 1.570; nova regressão HTTP).
- Frontend completo: **697 testes aprovados em 103 arquivos** (antes: 695; regressões de transição e fixtures).
- Testes direcionados finais: **22 aprovados em quatro arquivos**; outras execuções direcionadas também aprovadas, sem soma duplicada às suítes completas.
- Lint, typecheck, build, typecheck estrito do harness, build separado do harness, compileall e `git diff --check`: aprovados.
- Graphify atualizado por AST sem LLM e usado para verificar dependências de refresh, transição, histórico Shopify e Saúde dos Dados.

Logs em `/tmp/mugo-phase1-visual-final/`. Avisos não bloqueantes: Node local 26 versus engine 22 declarada, mensagens experimentais/JSDOM e aviso de chunk grande do build do harness. Sem alteração de dependências.

## Evidências visuais

Galeria local: `/tmp/mugo-phase1-visual-final/index.html`. Capturas individuais e JSON de resultados na mesma pasta. A galeria exclui capturas explicitamente nomeadas como debug; os arquivos iniciais de diagnóstico são mantidos separadamente para rastreabilidade e não aprovam o candidato final.

Exemplos finais: `meta-1440.png`, `meta-390.png`, `ga4-320.png`, `fbits-320.png`, `shopify-320.png`, `conexoes-768.png`, `saude-320.png`, `menu-390.png`, `tooltip-roas-320.png`, `refresh-running-390.png`, `refresh-cooldown-390.png`, `refresh-sucesso-390.png`, `refresh-erro-390.png` e `roove-recuperacao-parcial-390.png`.

## Git, publicação e limites

Branch main; HEAD 35e138b8ed1b67cba77606a4724c5e66458e6348 preservado. Os oito diffs paralelos continuam byte a byte idênticos ao backup anterior e ao snapshot desta rodada. Index vazio. Nenhum commit/push/deploy/migration; nenhuma escrita real em dados, credenciais, integrações ou providers.

O checkout contém integração anterior em diffs sobre HEAD antigo. Para publicar futuramente: preparar candidato isolado sobre a referência publicada 8bc88d73d38f36cb6f988b598445a9b1bf85054c, aplicar somente alterações aprovadas e conferir conteúdo exato. Não usar todo o diff contra HEAD como pacote automático. Manifesto/hash documenta arquivos, não autoriza staging de alterações paralelas ou publicação.

Pendências não impeditivas da homologação local: aparelhos físicos/Safari, sessão autenticada real, múltiplas sessões contra locks distribuídos reais e desempenho/RSS do Render. Depois de autorização/publicação, fazer smoke exclusivamente de leitura em frontend/backend e conferir versão efetiva dos dois serviços. Qualquer falha crítica desse smoke impede declarar o deploy concluído e exige avaliar rollback para a última release homologada.

## Adendo — bootstrap Meta no startup de produção

Correção pontual posterior à homologação visual: `server/app.py::startup_bootstrap` retorna antes de invocar o bootstrap quando o runtime é produção/Render. Qualquer marcador explícito de produção prevalece sobre aliases conflitantes. Configuração de seed não reativa o caminho. Nenhuma chamada, credencial, conexão existente ou fluxo OAuth foi removido.

A outra chamada está em `server/services/ads_sync.py::_pick_paid_connection`, como fallback quando uma sincronização autorizada não encontra conexão paga e não solicita uma conexão específica. Esse fluxo foi identificado e preservado; o bloqueio solicitado limita-se ao startup. O bootstrap não é removido nem bloqueado como operação explícita fora do startup.

Regressões em `server/tests/test_startup_meta_bootstrap.py`: oito combinações de produção/Render com configuração sintética válida não chamam o bootstrap; desenvolvimento conserva seu hook mockado; conexão paga existente é resolvida sem bootstrap; OAuth e vinculação explícita de ativos continuam funcionando com IO mockado. O lifespan da aplicação é exercitado; a função real de bootstrap nunca é executada.

Arquivos de implementação/teste adicionados ao candidato: `server/app.py` e `server/tests/test_startup_meta_bootstrap.py`. Manifesto da Fase 1 passa a 59 caminhos, com 55 arquivos de código/testes/estilos e quatro documentos. Resultados da validação do candidato atualizado ficam nos artefatos de preparação em `/tmp/mugo-phase1-rc-location.txt` (caminho do diretório da rodada). Nenhum commit/push/deploy ou acesso remoto foi realizado nesta correção.

Validação do adendo no candidato isolado: 1.567 testes backend aprovados, incluindo quatro novos testes de startup/conexão; a diferença em relação à árvore principal corresponde aos oito testes paralelos excluídos, não a testes desativados. Bootstrap real substituído antes da descoberta dos testes, com zero chamadas aos guards externos. Lint, typecheck, build, compileall e diff-check aprovados. O frontend do candidato havia passado com 696 testes (o teste paralelo adicional da árvore principal permanece excluído); o adendo não modifica frontend.

A primeira execução completa do teste novo de resolução de conexão encontrou um mock deixado por testes antigos de resiliência. O novo teste passou a capturar a função real na descoberta, preservando a validação e sem alterar os testes ou código paralelos. A suíte completa foi repetida com sucesso.

Risco residual de escopo: o fallback explícito no Ads Sync continua existindo quando não há conexão paga; não foi transformado em execução de startup nem removido. A proteção de startup só estará vigente em produção após uma publicação autorizada. Nenhum estado atual das variáveis secretas do Render foi presumido ou consultado nesta correção.
