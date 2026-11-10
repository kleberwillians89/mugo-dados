# MUGÔ DADOS — REGRAS DO AGENTE LOCAL

## Idioma
- Responda sempre em português do Brasil.
- Seja direto e objetivo.

## Regra principal: NÃO INVENTAR
- Nunca invente arquivos, funções, componentes, testes, schemas, rotas ou comportamentos.
- Toda afirmação sobre o código deve ser baseada em evidência obtida por ferramenta real.
- Use Read, Grep, Glob ou Bash antes de afirmar qualquer coisa sobre o repositório.
- Se não houver evidência suficiente, diga exatamente:
  "NÃO CONFIRMADO NO CÓDIGO."

## Caminho do projeto
O repositório real é:

/Users/k/Projects/mugo-dados

Nunca use ou invente caminhos como:
- /home/user
- /workspace
- /app
- /project

Antes de tarefas importantes, confirme o diretório real com:
pwd

## Ferramentas
- Execute ferramentas de verdade.
- Nunca escreva JSON de tool call como se fosse texto.
- Nunca simule saída de terminal.
- Nunca invente resultado de comando.
- Se um comando não foi executado, não diga que foi.

## Investigação
Antes de editar:
1. Leia o arquivo relevante.
2. Localize dependências relacionadas somente quando necessário.
3. Identifique a causa com evidência concreta.
4. Só então proponha ou faça a alteração.

Evite buscas globais desnecessárias.

## Evidência
Em diagnósticos, use:

CONFIRMADO
- Arquivo:
- Símbolo real:
- Evidência:
- Conclusão:

SUSPEITA
- Hipótese:
- Evidência parcial:
- O que falta verificar:

NÃO CONFIRMADO
- Informação que não pôde ser comprovada.

Nunca transforme SUSPEITA ou NÃO CONFIRMADO em fato.

## Código literal
Ao citar comportamento do código:
- use nomes reais encontrados no arquivo;
- copie somente pequenos trechos relevantes;
- não invente expressões equivalentes;
- não transforme trim em minLength;
- não transforme inputMode em validação;
- não deduza required sem evidência;
- não atribua validação à API se ela existir apenas no frontend.

## Testes
Nunca diga que um teste existe sem ler o arquivo de teste.

Ao mencionar teste existente, informe:
- arquivo;
- nome real do teste;
- comportamento realmente testado.

## Alterações
- Faça mudanças mínimas.
- Não refatore partes não relacionadas.
- Não altere arquitetura sem pedido explícito.
- Preserve o comportamento existente que não estiver relacionado ao problema.

## Verificação após alterações
Depois de editar, execute quando aplicável:

git diff --check
npm test
npm run lint
npm run build
git status --short
git diff

Se algum comando falhar, informe a falha real.
Nunca diga que passou sem executar.

## Git
Permitido sem confirmação:
- git status
- git diff
- git branch
- git log

Antes de:
- git commit

peça autorização.

Nunca execute:
- git push

## Produção e banco remoto
Nunca execute:
- git push
- vercel deploy
- netlify deploy
- supabase db push
- supabase migration up
- supabase functions deploy

Não faça alterações em banco remoto.

## Segurança
Nunca leia:
- .env
- .env.local
- arquivos de secrets
- tokens
- credenciais
- chaves privadas

.env.example pode ser lido quando necessário.

## Forma de trabalhar
Para tarefas pequenas:
1. entender;
2. localizar;
3. ler;
4. alterar;
5. testar;
6. mostrar diff.

Para bugs:
1. reproduzir ou identificar evidência;
2. localizar causa;
3. confirmar causa;
4. corrigir minimamente;
5. testar regressão;
6. mostrar resultado.

## Limite de confiança
Quando não tiver certeza, pare.

É melhor responder:
"NÃO CONFIRMADO NO CÓDIGO."

do que preencher lacunas com uma resposta plausível.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
