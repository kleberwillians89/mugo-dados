# Tarefas e Atendimento do CRM dentro do Mugô Dados

Fase 1, **somente leitura e só para a agência**:
- O CRM Mugô continua sendo onde a tarefa é criada e onde se responde no WhatsApp.
- O Dados só lê, ao vivo, pela função `dados-ops-api` do CRM. Nada é copiado.

Fluxo: Dados (Render) → `GET https://<crm>.supabase.co/functions/v1/dados-ops-api/{tasks|conversations|messages}?external_client_id=<id da empresa no Dados>`, com o header `X-Dados-Ops-Key`.

O CRM resolve organização e cliente pela tabela `external_integrations` (provider `mugo_dados`). O Dados nunca envia ids do CRM.

| Tela | Rota | Quem vê |
|---|---|---|
| Tarefas | `/tarefas` | agency_admin / platform_admin |
| Atendimento | `/atendimento` | agency_admin / platform_admin |

O cliente (client_admin/viewer) não vê essas telas: o menu fica escondido e o backend responde 403.

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

Uma conversa aparece na empresa quando o **contato do WhatsApp está vinculado ao cliente** no CRM (`whatsapp_contacts.client_id`). Para que a conversa de um contato apareça, vincule esse contato ao cliente no CRM.

## Tarefas: o que fica de fora

Ficam de fora as tarefas ligadas a parcela (`installment_id`), as de categoria que começa com "financ" e as arquivadas.
