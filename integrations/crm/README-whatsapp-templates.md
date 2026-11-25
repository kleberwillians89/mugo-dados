# WhatsApp Templates — MugôZap CRM integration

## Purpose
`Mugô Dados → Empresa → WhatsApp → Modelos de mensagens` now selects a source by tenant:
- **Cloud API stored in Mugô Dados**: existing `whatsapp_numbers` + native template APIs.
- **Mugô CRM / MugôZap**: new authenticated CRM Edge Function `dados-whatsapp-templates` reads and submits models using the **already stored CRM Meta token**. No copying of Meta credentials to Mugô Dados.
- **Ruah CRM brand bridge**: kept unchanged. Its separate bridge does not yet offer Meta template management; the UI states this rather than inventing a connection.

## Deployment order — NOT EXECUTED
1. Review `integrations/crm/migrations/0001_mugo_dados_whatsapp_org_links.sql` with the CRM owner and apply it in CRM Supabase only after approval.
2. Approve and add the explicit organization link for Mugô Dados company `388cd0b5-931e-4ff6-8427-aaffec170db7` to CRM organization `1dc27d95-d4c0-447f-a8e8-f0afb6a9f40f`, using the reviewed commented SQL. The source organization was verified via CRM read queries. This is **not** a regular CRM client: `external_integrations.client_id` is NOT NULL, so it cannot represent this org-level relationship.
3. Deploy `integrations/crm/supabase/functions/dados-whatsapp-templates/index.ts` as the **new** function `dados-whatsapp-templates` in CRM Supabase (with `verify_jwt=false` **only** because it authenticates server-to-server via `X-Dados-Ops-Key`). Do not replace the existing `dados-ops-api`, `mugozap-api` or WhatsApp webhook.
4. Confirm existing CRM Supabase secrets `DADOS_OPS_API_KEY`, `META_ACCESS_TOKEN`, `WABA_ID`, `GRAPH_API_VERSION` are configured server-side. Never print their values. The function verifies that the stored organization-owned CRM WhatsApp connection matches WABA_ID and uses reference `env://legacy-default`.
5. Deploy Mugô Dados backend on Render with existing `CRM_OPS_API_URL` and `CRM_OPS_API_KEY` (pointing to the same Supabase CRM project). No new Render secret required.
6. Deploy frontend Vercel. Select Mugô Agencia in Mugô Dados and verify connected via MugôZap, model list, create a disposable test **template for approval only**, and refresh approval status from Meta. Check Ruah still reads messages; confirm Roove remains isolated. Do not send messages or publish live campaigns as part of homologation.

## Permissions and guarantees
- FastAPI requires agency/client admin role on selected tenant.
- CRM Edge Function resolves the tenant via an **explicit** org link or existing active client-specific integration; it rejects missing links.
- For organization-owned Mugô WABA, CRM connection must have null client_id and match CRM org ID. For branded client-specific numbers, the connection client_id must match the integration client_id.
- The API never sends the Meta access token to Mugô Dados or the web. It does not send messages: POST only submits a template for Meta review. Templates have approval status; sending later requires approved models and opt-in.
- GET reads Meta's authoritative template status directly (paginated, currently 5×100 max).
- Ruah CRM bridge is unchanged and cannot silently use Mugô's WABA.
- New integrations cannot be inferred by matching company names or the fact they share a CRM organization.

## Remaining production prerequisites
- Review & apply new CRM schema/mapping and deploy the new CRM function (both not executed).
- Review new API endpoint authorization, Meta permission `whatsapp_business_management`, and template moderation state.
- Run authenticated end-to-end tests with an authorized Mugô account. Unit tests alone don't confirm real Meta approval.

### Respostas a conversas e avisos de tarefas

A resposta pelo Mugô Verso usa a conversa do CRM, a janela de atendimento de
24 horas e o mesmo envio manual do `mugozap-api`. Para habilitar o campo de
resposta, publique a versão atual da função `dados-whatsapp-templates` no CRM e
configure `DADOS_WHATSAPP_REPLY_TEAM_MEMBER_ID` com um membro ativo da organização
vinculada, cujo perfil ativo seja administrador ou gerente. A função usa o
`TASK_COMMAND_WORKER_KEY` do projeto CRM e a conexão existente.

Para avisar responsáveis por novas tarefas pelo número do MugôZap, configure no
backend do Mugô Dados `TASKS_WHATSAPP_TRANSPORT=mugozap`,
`TASKS_WHATSAPP_SENDER_CLIENT_ID` e `TASKS_WHATSAPP_TEMPLATE`. O template deve
estar aprovado e ativo em pt_BR, com um parâmetro posicional de texto no corpo.
O backend usa a configuração `MUGOZAP_*` existente. Cada responsável precisa
confirmar seu telefone e ativar os avisos no chat de tarefas.
