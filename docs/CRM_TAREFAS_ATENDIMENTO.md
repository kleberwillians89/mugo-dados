# Tarefas e Atendimento do CRM dentro do Mugô Dados

Fase 1, **somente leitura e só para a agência**:
- O CRM Mugô continua sendo onde a tarefa é criada e onde se responde no WhatsApp.
- O Dados só lê, ao vivo, pela função `dados-ops-api` do CRM. Nada é copiado.

Fluxo: Dados (Render) → `GET https://<crm>.supabase.co/functions/v1/dados-ops-api/{tasks|conversations|messages}?external_client_id=<id da empresa no Dados>`, com o header `X-Dados-Ops-Key`.

O CRM resolve organização e cliente pela tabela `external_integrations` (provider `mugo_dados`). O Dados nunca envia ids do CRM.

| O quê | Onde | Quem vê |
|---|---|---|
| Todas as tarefas do cliente | `/tarefas` (menu Operação) | agency_admin / platform_admin |
| Conversas do WhatsApp por contato | Aprovação → aba Mensagens | agency_admin / platform_admin |
| "Em andamento com a Mugô" | Aprovação (topo) | todos os membros da empresa |

O bloco "Em andamento com a Mugô" mostra só as tarefas com a **etiqueta `cliente`** no CRM. Cada uma aparece com título, status e prazo; observações, equipe e etiquetas não vão para o cliente.

`/atendimento` agora abre a Aprovação.

## Ligar (uma vez)

1. **Gere uma chave** longa e aleatória, por exemplo com `openssl rand -hex 32`.
2. **No CRM**, na pasta do projeto:
   - `npx supabase secrets set DADOS_OPS_API_KEY=<chave>`
   - `bash scripts/deploy-dados-ops.sh`
3. **No Render** do Dados, em Environment:
   - `CRM_OPS_API_URL=https://<projeto-crm>.supabase.co/functions/v1/dados-ops-api`
   - `CRM_OPS_API_KEY=<a mesma chave>`
4. **Ligue as empresas** rodando o SQL abaixo no Supabase **do CRM**.

Sem os passos 2 e 3, as telas mostram "A ligação com o CRM ainda não foi configurada". Sem o passo 4, mostram "Esta empresa ainda não está ligada a um cliente do CRM". Nenhum desses casos dá erro.

## Atendimento: de onde vêm as conversas

Uma conversa aparece na empresa quando o **contato do WhatsApp está vinculado ao cliente** no CRM (`whatsapp_contacts.client_id`).

Na aba Mensagens, cada contato cadastrado na Aprovação (Ana, Nasser…) é casado com a conversa dele pelo telefone. O casamento aceita o número com ou sem o 9º dígito. Conversas de outros contatos vinculados ao cliente aparecem em "Outros contatos deste cliente no CRM".

## Tarefas: o que fica de fora

Ficam de fora as tarefas ligadas a parcela (`installment_id`), as de categoria que começa com "financ" e as arquivadas.
