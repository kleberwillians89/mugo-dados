# Inteligência & Relatórios — candidato estratégico

## Diagnóstico confirmado

Base: `ac0c6e7`, main incluindo os PRs #6, #7 e #8. Branch `feat/intelligence-strategic-reports`, worktree `/tmp/mugo-strategic-reports-checkout`.

Graphify foi consultado sem reconstrução; o fluxo foi confirmado no código real. O PR #8 já gerava análises pelo pipeline canônico e previa relatório, mas exportava por `window.print()`, não oferecia histórico próprio nem gráficos comparativos. O prompt existente já exigia interpretação executiva, evidências e hipóteses. Uma suposta instrução para gerar posts/legendas: **NÃO CONFIRMADO NO CÓDIGO.** Não foi inventada uma causa no modelo.

## Implementação

- Interface reaproveitada, com resumo executivo, KPIs, variações, gráficos atual/anterior por indicador, diagnóstico, leitura por canal, oportunidades/riscos e plano de ação com indicador de acompanhamento.
- Perguntas e relatórios continuam separados; chat, conversas e recuperador contextual não foram reimplementados.
- Empresa vem do seletor e da autorização existente; períodos semanais (segunda-domingo) e mensais (calendário) são datas civis. O fuso atualmente adotado pelo pipeline é America/Sao_Paulo, explicitado no relatório. Não foi criado suporte fictício a configuração de fuso por tenant.
- Comparação usa valores/variações existentes. A janela anterior é de igual duração, conforme o pipeline; datas são exibidas. Um mês de 30 dias NÃO é apresentado como comparação com o mês anterior completo de 31 dias.
- Histórico carrega até 25 análises recentes, filtra registros concluídos e períodos calendário exatos, e seleciona a versão por ID. Não reconsulta dados atuais para reconstruir uma versão antiga. Intervalos personalizados não são rotulados falsamente como semana/mês.
- Fontes, métricas e análise já eram persistidas em `ai_analyses`. Novas gerações também preservam nome da empresa, fuso e cruzamentos/funil em `data_quality.report_context`, JSON existente. Nenhuma tabela ou migration nova.
- Registros antigos continuam consultáveis; se não têm nome congelado, usam o nome atual do cadastro. Indicadores/análise históricos permanecem os do snapshot. Versões antigas sem funil salvo não são reconstruídas com números atuais.

## Dados e IA

Geração continua em `generate_analysis` → `calculate_intelligence_snapshot` → métricas/política canônicas → provedor → grounding numérico/temporal/causal → análise persistida. Não foram modificados prompts, ferramentas, conectores ou `/ask`; a única alteração no serviço de geração é metadado adicional do snapshot salvo.

O relatório usa somente métricas disponíveis no snapshot: não soma receita atribuída entre plataformas, não deduplica vendas por inferência, não fabrica metas ou tendências. Comparativos visuais não são séries diárias nem prova de causalidade. Funil é exibido somente quando congelado e confirmado nas evidências GA4. Dados detalhados que não integram o snapshot canônico (por exemplo, dimensões de landing page/região, quando ausentes) não são inventados por este módulo. Recomendações dependem das evidências existentes; nenhuma lista é preenchida artificialmente.

## PDF real

Novo GET `/api/intelligence/reports/{analysis_id}/pdf?kind=weekly|monthly` reutiliza autenticação e resolução de tenant. Valida UUID, escopa a consulta por tenant/ID/status e rejeita registro de outra empresa. A exportação é leitura; não chama IA nem sincroniza providers.

ReportLab 4.5.1 gera bytes PDF A4 com capa, versão, resumo, KPIs, gráficos vetoriais, canais, diagnóstico, recomendações, plano, fontes e metodologia. Texto é escapado, não há carregamento de HTML/URLs externas. Tabelas repetem cabeçalho e podem dividir linhas. Conteúdo limitado a 200 mil caracteres serializados, 100 métricas, 30 insights e 30 ações, com arquivo máximo de 2 MB. A renderização roda em thread sob o admission control/RSS existente; leituras normais continuam disponíveis. Exportação pode retornar indisponibilidade temporária se outro processamento pesado estiver ativo.

A API retorna `application/pdf`, attachment, no-store e nosniff. O frontend usa a sessão existente, valida MIME/tamanho e baixa o Blob com empresa/período no nome. Cancelamento/troca de tenant descarta respostas atrasadas. Não usa impressão como exportação.

Dependência de produção: `server/requirements.txt` inclui ReportLab. `server/requirements-test.txt` inclui pypdf para validação local. Escolha: geração vetorial sem navegador headless em produção e sem infraestrutura adicional.

## Evidências executadas

- 191 testes backend direcionados: relatório, geração, ferramentas, continuidade, contexto e grounding numérico/temporal; oito novos testes PDF/acesso, mais assertions da persistência dos metadados.
- 135 testes frontend: relatórios, página Inteligência, mobile, priorização, histórico e API de conversas.
- Lint, typecheck, build, compileall e `git diff --check`.
- PDF sintético A4 de 3 páginas e relatório extenso de 11 páginas, validados com pypdf/pdfinfo e renderizados com Poppler. Conferidos capa, margens, cabeçalhos repetidos, gráficos, última métrica, acentos e paginação. Fontconfig emitiu aviso de cache local, sem impedir renderização.
- Chromium real local, componentes reais e fixtures identificadas, em 390×900 e 1440×900: largura global igual ao viewport, resumo/KPIs/comparativos renderizados, sem erro JS capturado. Seleção de histórico e download real de arquivo `%PDF-` confirmados com respostas HTTP mockadas e modo de desenvolvimento local já existente. Isso NÃO valida login/autorização real; o backend teve testes de autorização com mocks separados.
- Evidências em `/tmp/mugo-strategic-evidence/`: PDFs, PNGs das páginas, screenshots e `browser-results.json`. Fixtures e harness temporário não fazem parte da release.

As falhas iniciais da geração vinham da suposição nova de `snapshot.client` sempre presente nas fixtures; corrigido com fallback seguro ao ID já autorizado. A expectativa do título da página foi atualizada. A tradução do PDF também recebeu correção de colisão de variável, antes da validação final. Nenhum teste foi desativado ou validador flexibilizado.

## Arquivos do candidato (16)

- `docs/intelligence-strategic-reports-audit.md`
- `server/requirements.txt`
- `server/requirements-test.txt`
- `server/routes/intelligence.py`
- `server/services/intelligence.py`
- `server/services/intelligence_reports.py`
- `server/tests/test_intelligence.py`
- `server/tests/test_intelligence_reports.py`
- `src/app/api.ts`
- `src/app/intelligenceReport.ts`
- `src/app/intelligenceTypes.ts`
- `src/components/intelligence/IntelligenceReports.tsx`
- `src/components/intelligence/IntelligenceReports.test.tsx`
- `src/pages/Intelligence.tsx`
- `src/pages/Intelligence.test.tsx`
- `src/styles/intelligence-reports.css`

## Homologação e publicação

Candidato funcional validado localmente, não declaração de funcionamento em produção. Nenhuma credencial foi lida; não houve análise paga, sync, exclusão real, migration, commit, push ou deploy.

Em ambiente autorizado: confirmar instalação da dependência, autenticação de dois usuários em tenants distintos, gerar semana/mês com fontes reais, conferir períodos/cobertura, registrar uma versão e depois atualizar dados para comprovar imutabilidade, exportar PDF e comparar com a versão exibida. Testar erro de provider sem perda do relatório anterior, tenant sem fonte e tentativa de acessar UUID de outro tenant. Geração real com IA requer autorização de custo.

Limites reais: histórico mostra 25 análises recentes; gráficos apresentam até oito pares comparáveis, não séries diárias; o fuso segue o padrão atual do produto; memória estruturada/feedback continuam fora deste módulo. Cobertura completa de todas as dimensões das integrações depende do snapshot canônico disponível, não de inferência do relatório.

Sem mudança de schema: rollback futuro consiste em retornar frontend/backend ao SHA anterior `ac0c6e7` (usar SHA completo do manifesto), preservando os JSONs extras já salvos. Nenhum dado precisa ser apagado. A produção só deve ser aprovada após homologação autenticada e de dados reais; não foi publicada nesta tarefa.

## Preservação dos candidatos anteriores

Os oito arquivos paralelos conferem com os hashes de referência. Continuidade e contexto conferem com os manifestos existentes. O manifesto anterior de relatórios antecede a integração: o worktree de relatórios está limpo em `59189aa`, e `Intelligence.tsx`/seu teste coincidem com esse HEAD, embora divirjam do manifesto antigo. Nenhum desses worktrees foi editado nesta tarefa; não se afirma equivalência do candidato integrado com um manifesto obsoleto.

## Homologação final — 21/10/2026

Trabalho restrito ao worktree deste candidato. Graphify consultado em cópia local do grafo, sem reconstrução; como o grafo antecede módulos novos, o fluxo foi confirmado nos arquivos atuais. Nenhuma correção de código foi necessária nesta rodada.

### Ambiente e alcance da evidência

A ferramenta de navegação não disponibilizou sessão autenticada. A configuração completa de backend/IA também não está disponível no ambiente herdado do processo. Arquivos de credenciais não foram lidos. Isso não demonstra inexistência de credenciais em outros ambientes; demonstra apenas ausência de acesso autorizado utilizável nesta execução.

Não foram consultados dados reais de nenhum tenant, executadas chamadas pagas, sincronizações ou escritas em produção. A geração semanal/mensal REAL e sua correspondência com fontes externas NÃO estão homologadas.

### Matriz de homologação

| Cenário | Resultado | Evidência | Limitações | Bloqueio para produção |
|---|---|---|---|---|
| Endpoints, autenticação e escopo | Conferido no código; testes locais aprovados | `_context` exige usuário e tenant resolvido; geração, histórico e PDF reutilizam esse contexto; PDF filtra tenant/UUID/status | Sessão e memberships reais não exercitadas | Validar login e autorização no ambiente autorizado |
| Geração semanal e mensal | Aprovada com mocks; real bloqueada | Testes frontend de intervalos e fluxo; testes backend de geração | Nenhuma chamada real ao modelo ou leitura real de métricas | Gerar os dois formatos no tenant autorizado |
| KPIs, comparativos e gráficos | Aprovados localmente | Snapshot sintético com investimento 100, anterior 80, variação 25%; mesmos valores no PDF; gráficos apenas para pares comparáveis | Não comprova reconciliação contra providers reais | Conferir valores, cobertura e unidades nas fontes efetivas |
| Evidência, hipótese e causalidade | Guardas aprovadas em testes | Grounding numérico, temporal e causal; testes de recuperação e referências entre tenants | Qualidade de uma nova resposta real do modelo não avaliada | Revisar diagnóstico e recomendações reais |
| PDF semanal e mensal | Arquivos reais válidos, dados sintéticos | `weekly-SINTETICO.pdf` e `monthly-SINTETICO.pdf`, três páginas A4 cada; pypdf e renderização Poppler | Não contêm métricas de produção | Comparar PDF e interface da mesma versão real |
| Histórico e imutabilidade | Aprovados com mocks | Seleção por ID, sem nova geração; teste de snapshot não mutado e metadados congelados | Histórico limitado a 25 análises; persistência real não exercitada nesta rodada | Confirmar leitura de versões salvas no ambiente autorizado |
| Isolamento entre clientes | Código e testes locais aprovados | Consulta PDF escopada, registro estrangeiro negado, geração cross-tenant bloqueada em testes | Sem tentativa em tenants reais; nenhum dado estrangeiro acessado | Exercitar permissões somente com tenants/usuários de teste autorizados |
| Download e falhas | Aprovados localmente | Chromium baixou PDF de 5.479 bytes; validação `%PDF-`; testes de falha preservam relatório | HTTP mockado, autenticação local de desenvolvimento | Confirmar download autenticado com backend real |
| Responsividade | Aprovada nos componentes locais | Chromium 390×900 e 1440×900; scrollWidth igual a 390/1440; screenshots inspecionados, sem erro JS capturado | Harness de componentes; shell autenticado não homologado | Conferir a navegação autenticada no ambiente final |
| Paginação extensa | Aprovada em teste | Fixture de 75 métricas, última métrica preservada, PDF multipágina | Dados sintéticos; evidência visual extensa da implementação anterior reutilizável | Sem defeito local demonstrado; revisar relatório real extenso se houver |
| Validação estática e regressão | Aprovada | 191 testes backend + 73 adicionais; 135 frontend; lint, typecheck, build, compileall e diff check | Testes com mocks não substituem homologação real | Nenhum bloqueio local encontrado |

### Resultados e artefatos desta rodada

Logs e artefatos em `/tmp/mugo-strategic-homologation/`: `backend.log`, `integrations.log`, `frontend.log`, `lint.log`, `typecheck.log`, `build.log`, `results.json`, `browser-results.json`, screenshots `ui-390.png`/`ui-1440.png`, PDFs semanal/mensal e arquivo baixado em `downloads/`.

Os 73 testes adicionais abrangem `test_intelligence_business_layer`, `test_intelligence_campaign_context`, `test_intelligence_temporal_recovery` e `test_intelligence_observability`, com conexões de rede bloqueadas no processo de testes. Os outros 191 backend e 135 frontend foram repetidos com os mesmos módulos registrados na implementação.

A inspeção confirma que relatórios usam o snapshot e o pipeline existentes, incluindo o contexto executivo do read model, contexto comercial, contexto de negócio e fontes autorizadas. A geração atual é permitida a membros, inclusive viewer, conforme contrato existente; isso não concede permissão de sincronização. Exportar PDF não chama o modelo nem atualiza providers.

Limitações anteriores mantidas: fuso padrão America/Sao_Paulo; janela anterior de igual duração; até oito pares visuais; dimensões fora do snapshot não são inventadas; registros antigos podem usar o nome atual do cadastro quando não têm nome congelado.

**Veredito: NO-GO para produção.** O candidato passou na validação local, mas faltam sessão/ambiente autorizado, geração real semanal e mensal, reconciliação de indicadores por fonte e conferência de histórico/PDF autenticados. Não há evidência para declarar a homologação real concluída. Nenhuma nova falha de código foi reproduzida nesta rodada; o único arquivo permanente alterado foi este relatório.

## Preparação de publicação controlada

Autorização recebida para commit, push, PR e publicação condicionada às verificações operacionais. Main remota e base do candidato conferidas em `ac0c6e7697f76b5c3b90d63bfa6c51f648d4af77`, sem divergência ou conflito. Dezesseis arquivos da entrega, sem alterações de migrations, roteamento, configuração Render/Vercel ou conectores.

Validação repetida: 264 testes backend e 135 frontend aprovados; lint, typecheck, build e diff check aprovados. Nenhuma lógica funcional foi alterada nesta preparação. O check do staging detectou espaços finais em duas linhas do arquivo novo `intelligence_reports.py`; foram removidos, e os oito testes do PDF foram repetidos antes do commit.

Referências anteriores para rollback:

- Main anterior: `ac0c6e7697f76b5c3b90d63bfa6c51f648d4af77`.
- Backend público: `/api/version` informa esse SHA completo, environment production; `/health` respondeu 200 e revision `ac0c6e7697f7` após uma primeira tentativa expirar.
- GitHub registra deployment Vercel Production `7237570372`, sucesso, SHA `ac0c6e7697f76b5c3b90d63bfa6c51f648d4af77`, URL `https://mugo-dados-ijrpekm9d-mugos-projects-aa2618ee.vercel.app`; dashboard `https://vercel.com/mugos-projects-aa2618ee/mugo-dados/3JLyVs7hD3btn3MtZoCuTuuCCk2S`.
- Domínios frontend raiz e `/inteligencia` responderam 200. A associação exata do alias público com o deployment não foi confirmada em API/painel administrativo. Ausência de SHA no bundle de entrada não prova divergência: a constante definida no Vite não é referenciada pelo código da aplicação.
- OpenAPI público da API anterior responde 200 e ainda não contém `/api/intelligence/reports/{analysis_id}/pdf`, esperado antes desta release.

Dependências: ReportLab 4.5.1 consta em `server/requirements.txt`. O `render.yaml` versionado usa rootDir server e `pip install -r requirements.txt`. Isso comprova a configuração do repositório, não a configuração efetiva do painel nem a instalação no processo de produção. Nenhuma migration necessária.

O GitHub confirma integração Vercel e deployment Production para main; configurações efetivas de auto-deploy e rollback do Render/Vercel e associação do alias ainda exigem acesso administrativo. Não há CLI das plataformas nem acesso herdado às suas APIs disponível nesta execução. Acesso seguro foi solicitado sem pedir tokens ou credenciais. O PR não deve ser integrado enquanto essas verificações obrigatórias permanecerem pendentes.

Após confirmação operacional, conferir instalação ReportLab no build do Render, o novo SHA em `/api/version`, o endpoint no OpenAPI, o deployment Vercel associado ao domínio e os smoke tests autenticados. Não promover deployments antigos nem alterar aliases. Para rollback, utilizar apenas mecanismo confirmado das plataformas ou reversão Git explicitamente inspecionada que preserve os dados; não foi executado rollback nem sync do Blueprint.
