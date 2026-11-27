# Calendário: Direcionamento Criativo e Encaminhamento do Briefing

## 1. Direcionamento Criativo (janela do conteúdo no Calendário)

- Primeiro bloco da edição (`src/components/studio/CreativeDirection.tsx`), só para a equipe (`canManage && !clientMode`).
- Campos: título/conceito, textos necessários, referências, instruções para a peça e briefing de referência (opcional).
- Escrita livre, sugestão da IA ou os dois. A IA (`POST /studio/calendar/items/{id}/creative-direction/suggest`)
  **não grava nada**. A sugestão aparece à parte e só entra no texto quando a pessoa clica em Usar, Substituir,
  Acrescentar ou "Preencher só os campos vazios". Depois disso, a pessoa ainda salva a pauta.
- Gravado em `studio_calendar_items.creative_direction` (jsonb, migração `20270127_000140`), pelo mesmo PATCH da pauta.
  É uma coluna própria, separada de `signals`, para que nenhuma geração da IA (briefing, esteira) sobrescreva o texto.
- A edição entra no histórico do post ("editou o direcionamento criativo"). O cliente não recebe o campo (`client_items`)
  nem pode alterá-lo (`CLIENT_FIELDS`).
- Quem cria vê o direcionamento: ao "Enviar para…", a tarefa da pessoa leva no topo um bloco **DIRECIONAMENTO CRIATIVO**
  e, no fim, um **BRIEFING DE REFERÊNCIA**. Esse briefing é o escolhido no bloco ou, se a pauta veio da Matriz, o
  briefing vinculado à Matriz (só leitura). Nada do briefing é copiado para a pauta.
- A ação **Gerar briefing com IA** (e "Refazer com IA") saiu da janela. O briefing que a pauta já tinha continua
  visível, copiável e enviável. O endpoint antigo continua ativo para a esteira de agentes.

## 2. Briefing: bloco Encaminhamento

"Levar para" e "Quem faz o quê" viraram um só bloco: destino, função, responsável, prazo, recado e o botão
**Confirmar encaminhamento**. Ele chama os mesmos serviços de antes (`POST /briefs/{id}/send/{destino}` e
`POST /briefs/{id}/tasks`), sem criar outro sistema de tarefas, e mantém o histórico (`destinations` e `tasks` do briefing).
Se o destino responder "falhou", a tarefa não é criada e aparece "Tentar de novo".

## 3. Ponto de conexão: aprovação da Matriz no Calendário (fica para depois do merge da PR da Matriz)

Não implementado nesta PR. A API para aprovar a matriz inteira, com um único registro de solicitação versionado, já
está na `main` (#477): `submitMatrixApproval(matrixId)` em `src/app/contentOps.ts`, que chama
`POST /content-ops/matrix/{id}/approval/submit`.

Para ligar o botão depois:
1. Em `src/pages/Calendar.tsx`, na barra do mês (equipe), mostrar "Enviar Matriz para aprovação interna" quando houver
   pautas com `origin === "matriz"` no período.
2. Descobrir a matriz: usar o `matrix_id` que a PR da Matriz expuser ao Calendário. Hoje o item só guarda
   `matrix_opportunity_id`.
3. Chamar `submitMatrixApproval(matrixId)` e mostrar `approval_status`. Não mexer em `ContentMatrix.tsx` nem em
   `studio_matrix.py`.
