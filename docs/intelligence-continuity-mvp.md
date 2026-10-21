# Inteligência — entrega independente de continuidade

## Implementado nesta entrega

- Reutiliza `ai_conversations` e `ai_messages`, existentes na migration `20260802_000021_intelligence_workspace.sql`.
- Restaura a última conversa pelo backend, escopada pelo tenant resolvido e pelo usuário autenticado; nenhuma mensagem é adicionada a localStorage/sessionStorage.
- Perguntas e respostas concluídas já eram persistidas pelo `/ask`. Nova conversa agora também é persistida vazia. A primeira pergunta dá título a uma conversa vazia ainda chamada “Nova conversa”.
- Selecionar uma conversa registra sua retomada com `updated_at`, permitindo restaurar a seleção após reload. GETs continuam sem escrita.
- Lista paginada de metadados (25 por leitura, até 200 na interface); restauração das últimas 100 mensagens em ordem cronológica. Não há coleta da coleção inteira.
- Renomeação de título e exclusão explícita e confirmada da própria conversa. A exclusão depende da FK existente `ai_messages.conversation_id ... ON DELETE CASCADE`; não toca métricas, conexões ou análises.
- IDs de tenant/usuário de payloads não autorizam consultas. Backend usa `_context`; filtros das mutações sempre incluem ID, tenant e usuário. Nenhuma mutação aceita alvo vazio.
- Leituras privadas não usam o coalescimento de GETs indexado apenas por tenant. Frontend também confere tenant/usuário retornados, aborta leituras anteriores e remonta ao trocar a identidade.
- Respostas históricas preservam suas fontes e períodos textuais. Não recebem KPIs do snapshot atual e não são fornecidas ao modelo como evidência numérica.

## Limites deliberados

- Esta entrega restaura o registro e a seleção da conversa. **O histórico ainda não é contexto do modelo**: o motor investigativo permanece inalterado. Perguntas abertas continuam aceitas; a cobertura efetiva depende das ferramentas existentes.
- Para consultar outro período, o usuário ainda deve selecioná-lo. Resolver “na semana anterior” automaticamente e recuperar referências de acompanhamento é a entrega seguinte.
- Rascunhos não enviados e perguntas que falham antes da persistência existente do `/ask` ainda não são salvos. Falha entre as gravações de pergunta/resposta pode deixar pergunta sem resposta; a interface a identifica, sem inventar sucesso ou reenviar automaticamente.
- Não há expiração automática de registros nesta entrega. Os limites são de leitura/contexto, não uma promessa de eliminação por idade. Exclusão manual por conversa é permanente; dados mais antigos continuam no backend até exclusão explícita.
- Corrigir título não reescreve respostas, fatos ou evidências. Correções semânticas, preferências, hipóteses e decisões confirmadas exigem a próxima entrega.

## Próximas entregas independentes

1. **Memória contextual e feedback:** taxonomia explícita (fato verificado, hipótese, preferência, decisão, obsoleto), origem verificável, confirmação do usuário, atualização/correção/exclusão e política de retenção/expiração. Recuperação limitada por tenant, usuário e conversa; mensagens antigas nunca entram na lista de valores canônicos atuais. Vincular acompanhamentos ao contexto sem permitir que texto livre escolha tenants, credenciais ou SQL. Manter o orçamento atual e explicar falta de ferramentas.
2. **Relatórios:** o candidato já existente em `/tmp/mugo-intelligence-reports-checkout` foi preservado e não foi misturado nesta branch. A integração será separada, após homologação da continuidade e da memória.

## Homologação e publicação

- Sem alterações de schema/RLS, migrations executadas ou chamadas reais a Supabase/IA.
- Testes usam mocks e verificam filtros/contratos; não comprovam o estado efetivo da FK nem a configuração do banco em produção.
- Backend com endpoints aditivos deve ser publicado antes do frontend. Endpoints existentes mantêm os contratos. A janela de mensagens passa das primeiras 100 para as últimas 100.
- QA real pendente: retorno à página/reload, troca de usuário e tenant, retomada de conversa antiga, criação vazia, falhas de rede, renomeação e exclusão por usuário de teste em ambiente de homologação.
- Exclusão foi testada apenas com mocks; nenhuma conversa real foi removida. Validar a FK por leitura segura antes da homologação de exclusão.

## Validação local desta entrega

- 167 testes backend direcionados aprovados.
- 139 testes frontend direcionados aprovados, incluindo navegação do App e isolamento das leituras privadas.
- Typecheck, build, lint direcionado e diff check aprovados.
- Sem homologação real, chamadas pagas, consultas a dados remotos ou exclusões reais.

## Arquivos da entrega

- `docs/intelligence-continuity-mvp.md`
- `server/routes/intelligence.py`
- `server/services/intelligence.py`
- `server/services/intelligence_conversations.py`
- `server/tests/test_intelligence_conversations.py`
- `src/App.tsx`
- `src/app/api.intelligenceConversations.test.ts`
- `src/app/api.ts`
- `src/app/intelligenceTypes.ts`
- `src/components/intelligence/ConversationHistory.test.tsx`
- `src/components/intelligence/ConversationHistory.tsx`
- `src/pages/Intelligence.test.tsx`
- `src/pages/Intelligence.tsx`
- `src/styles/intelligence-conversations.css`
