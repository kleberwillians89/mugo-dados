# Inteligência — recuperação contextual incremental

## Escopo e arquitetura

Primeiro incremento da segunda entrega, conforme a opção de divisão autorizada: recuperação contextual segura. Memória estruturada e feedback **não estão implementados** neste candidato.

Worktree: `/tmp/mugo-intelligence-context-checkout`.
Branch: `feat/intelligence-contextual-retrieval`.
Base Git: `1a7e9934541386ea40e7463d8d9b58879f0584d4`, mais os 14 arquivos não commitados da entrega `feat/intelligence-conversation-continuity`. Esta é uma dependência explícita, não um patch autônomo contra main.

Graphify consultado sem reconstrução do grafo; símbolos e fluxo confirmados no código. A busca direcionada nas rotas/serviços de Inteligência e na migration do workspace não encontrou armazenamento de feedback ou memória semântica. `memory_budget` controla recursos do processo, não memória da empresa. Não se afirma ausência global de outras estruturas fora desse escopo.

Fluxo: autorização existente → histórico privado existente → recuperação determinística de intenção/período → ferramentas existentes → evidências canônicas novas → validadores existentes → persistência existente.

- `recover_context` usa no máximo seis mensagens recentes, com orçamento de 1.800 caracteres de perguntas e máximo de 600 por pergunta. Somente perguntas do mesmo tenant, usuário e conversa podem contribuir. Considera o último turno de usuário válido, sem mesclar tópicos contraditórios de turnos antigos.
- Um vocabulário fechado de temas (campanhas, vendas, marketing, estratégia, operação) é extraído localmente. Não se envia texto histórico ao modelo. Perguntas abertas independentes continuam no fluxo anterior.
- O JSON existente de mensagens guarda `context_topics` e `context_request_period` definidos pelo backend. Servem apenas à continuidade de intenção, nunca a métricas ou autorização. Nenhuma migration.
- Mês e semana anteriores usam calendário; período anterior usa janela de igual duração. A continuação usa o último período resolvido quando a seleção da interface permanece igual. Uma seleção diferente prevalece como âncora. O período efetivamente consultado é persistido nas mensagens e no snapshot.
- “Qual campanha?” provoca nova investigação: nomes/IDs de campanhas antigos não são recuperados como entidades verificadas. A identidade e as métricas devem vir das ferramentas autorizadas.
- Referências sem tema inequívoco pedem esclarecimento. Comparação contextual entre períodos retorna limitação parcial explícita, sem consultar o modelo nem inventar variação. O envelope público de `/ask` permanece igual.
- “Por que isso aconteceu?” herda apenas tema/período, com ressalva de causalidade. Grounding numérico, temporal e causal continuam no pipeline original.
- Permanecem uma execução de ferramenta e duas chamadas de modelo no máximo; limites de entrada, saída, tempo e autorização não foram alterados. Não há recuperação de textos antigos como números confiáveis.

## Limitações e próxima entrega

Não há resolvedor geral de linguagem/referências: temas fora do vocabulário, entidades ambíguas e comparações de dois períodos exigem esclarecimento ou consultas separadas. Não há ainda memória estruturada, confirmação/correção/exclusão de memórias, feedback ou aprendizado contextual persistente além da intenção da conversa. Edição/exclusão de conversas continua sendo a capacidade da entrega anterior; não equivale a CRUD de memória.

Próximo incremento independente: auditar armazenamento reutilizável para registros tipados (fato verificado, hipótese, preferência, decisão confirmada e obsoleto), com origem, datas, validade, confiança e confirmação autenticada. Ações explícitas por proprietário devem criar/revisar/invalidar esses registros, com retenção e exclusão limitadas. Feedback deverá influenciar preferências/contexto, nunca promover texto antigo a evidência numérica, nem retreinar o modelo. Não foi criado schema especulativo para antecipar esse trabalho.

## Validação local

Comando executado:

```sh
PYTHONPATH=server:server/tests /tmp/mugo-memory-venv/bin/python -m unittest test_intelligence_context test_intelligence_conversations test_intelligence test_intelligence_tools test_intelligence_numeric_grounding test_intelligence_temporal_compatibility
```

Resultado: **183 testes aprovados**, incluindo 16 novos testes em `server/tests/test_intelligence_context.py`. A primeira execução encontrou regressão na detecção de “Compare os indicadores”; foi corrigida e a validação final passou. O teste existente de resposta parcial via HTTP permaneceu verde.

Regressões novas cobrem datas/calendário e acompanhamentos sucessivos, alteração da seleção de período, campanhas sem identidade presumida, causalidade, ambiguidade, troca de proprietário/tenant/conversa, conteúdo histórico malicioso, turnos contraditórios, limites, ausência de fontes e integração com o pipeline real de validação usando ferramentas e modelo mockados. Correção/remoção do histórico foi simulada nas fixtures para comprovar ausência de cache; isso não implementa CRUD de memória estruturada.

Compileall dos três arquivos Python afetados e `git diff --check` aprovados. Nenhum frontend foi alterado nesta entrega; não houve instalação, consulta remota, exclusão real, IA paga ou operação de publicação.

## Arquivos adicionais à entrega anterior

1. `server/services/intelligence.py` — conexão do recuperador ao `/ask` e metadados de intenção no JSON existente.
2. `server/services/intelligence_context.py` — recuperador determinístico e limitado.
3. `server/tests/test_intelligence_context.py` — regressões direcionadas.
4. `docs/intelligence-contextual-retrieval.md` — arquitetura, limites e homologação.

## Homologação necessária

Em ambiente de teste autorizado, usar dois usuários e tenants distintos: restaurar conversa, fazer acompanhamento, alterar período e trocar de empresa. Conferir que as datas exibidas correspondem ao snapshot consultado e que referências ambíguas são explicadas. Validar perguntas abertas fora do vocabulário e mensagens de ausência de fonte; nenhuma análise paga foi executada nesta rodada. Confirmar comportamento visual do aviso parcial. Comparações contextuais e memória/feedback permanecem entregas futuras, não critérios já concluídos.
