# Central de Automações (WhatsApp oficial + Google Calendar)

Tela: **Administração → Automações** (`/automacoes`), só equipe Mugô (platform_admin/agency_admin).

## 1. O que a auditoria encontrou (antes de codar)

| Área | Onde já existia | Decisão |
|---|---|---|
| Envio de WhatsApp | `mugozap-api` do CRM (número oficial, Cloud API). O Dados já chama por `studio_messages.mugozap_send`. O CRM confere template aprovado, idempotência e grava o histórico canônico. | **Reutilizado.** A fila nova envia pelo mesmo caminho, com a mesma chave em todo retry. |
| Webhook da Meta | `whatsapp-webhook` do CRM. Já repassa ao Dados a resposta do convite (`/api/hooks/crm`, `invite_reply`). | **Reutilizado.** O hook agora aceita também `message_status`. |
| Catálogo de templates | CRM `whatsapp_message_templates` (sincronizado da Meta). | O Dados lê direto da Meta (somente leitura) para mostrar o status real. |
| Tarefas | CRM: `team-notification-worker` (`task_assigned`), `task-reminder-worker` (`mugo_lembrete_tarefa`), `team-daily-brief-worker` (`mugo_resumo_diario_equipe`, seg a sex). | **Fica no CRM.** O Dados mostra como "Disparada pelo CRM" e nunca envia (evita duplicidade). |
| Financeiro | CRM: Asaas (`asaas-billing`, `asaas-webhook`), `collection-cadence-worker` (`mugo_cobranca_link_v1`, `mugo_alerta_pagamento_pendente`), `collection-notification-worker`. | **Fica no CRM.** Mesma regra. |
| Aprovações | Dados: link seguro com validade (`studio_approval_requests`, token cifrado), `/aprovar/{token}`, envio `mugo_conteudo_aprovacao` e lembrete manual. Cliente aprova/pede ajuste → `studio_team_events` → CRM cria tarefa e avisa o responsável. | **Reutilizado.** Novo: lembrete automático, "ajuste concluído" e "conteúdo publicado" confirmado no Instagram. |
| Relatório de sexta | Dados: `studio-weekly-digest` envia `mugo_convite_resumo` só se o relatório puder ser montado; a resposta volta pelo CRM. | **Estendido:** respostas "Resumo semanal", "Período completo" e "Agora não"; relatório separa faturamento total de receita atribuída. |
| Calendário | Dados: calendário de conteúdo (`/calendario`). Não havia Google Calendar. | **Novo:** sincronização do Google Calendar da Mugô, com as reuniões aparecendo na agenda existente. |

## 2. Tabelas e migração

`supabase/migrations/20261113_000062_automation_center.sql` (aditiva, pode rodar de novo sem erro):

| Tabela | Para quê |
|---|---|
| `whatsapp_template_catalog` | Espelho de `GET /{WABA_ID}/message_templates` (status, categoria, idioma, variáveis, botões). |
| `automation_definitions` | Uma linha por automação: dono (`dados`, `crm` ou `tecnico`), público, gatilho, liga/desliga, horário, antecedência, ordem das variáveis. |
| `automation_outbox` | Fila persistente. `idempotency_key` única, trava por `claim_token` com `SKIP LOCKED`, tentativas, backoff, status de entrega. |
| `automation_responses` | Respostas recebidas (botões e texto). |
| `automation_team_members` | Equipe Mugô (e-mail do Google + WhatsApp) para avisos internos. |
| `automation_recipient_prefs` | Opt-out e consentimento de Marketing por telefone. |
| `google_calendar_connection` | Conta corporativa autorizada (tokens cifrados), agenda escolhida, `syncToken` e canal de webhook. |
| `calendar_events` | Eventos sincronizados, únicos por `(calendar_id, google_event_id)`. |
| `studio_client_contacts.email` | Nova coluna opcional: liga o participante do convite à empresa certa. |
| `oauth_sessions` | Novo provedor `google_calendar` na constraint. |
| `claim_automation_outbox(limit, token)` | Função que pega lotes com trava (dois workers nunca pegam a mesma linha). |

A migração foi aplicada e reaplicada num Postgres 16 local. A trava foi testada com dois processos simultâneos: 30 linhas divididas, nenhuma em comum.

## 3. Situação de cada template

O status de aprovação **não** é definido aqui: só aparece depois de **Sincronizar com a Meta**.
"Dono" diz quem dispara. As do CRM ficam só visíveis no Dados.

| Template | Dono | Público | Gatilho no código | Observação |
|---|---|---|---|---|
| `mugo_reuniao_interna` | Dados | Equipe | Google Calendar, 24h antes (reunião só com a equipe) | Variáveis previstas: nome, título, data, hora |
| `mugo_reuniao_lembrete` | Dados | Cliente | Google Calendar, 24h antes (participante é contato de **uma** empresa) | nome, marca, título, data, hora |
| `mugo_agendamento_confirmado` | Dados | Cliente | Participante do cliente **aceitou** no Google | nome, dia, hora (igual ao CRM) |
| `mugo_conteudo_aprovacao` | Dados | Cliente | Tela Aprovação (já existia) | Botão `/aprovar/{token}` |
| `mugo_lembrete_aprovacao` | Dados | Cliente | Job, no máximo 1 a cada 48h por pedido aberto | Mesmo link, token cifrado na fila |
| `mugo_ajuste_concluido` | Dados | Cliente | Item que **o cliente** rejeitou volta para revisão/aprovado | nome, marca, título |
| `mugo_conteudo_publicado` | Dados | Cliente | Item publicado **e** post encontrado no Instagram da empresa (±48h) | nome, marca, título, link |
| `mugo_agenda_semana` | Dados | Cliente | Tela Aprovação → Mensagens (já existia) | |
| `mugo_convite_resumo` | Dados | Cliente | Sexta 10h15 (job existente), só com relatório válido | Botões: Resumo semanal / Período completo / Agora não |
| `mugo_relatorio_pronto` | Dados | Cliente | Disparo explícito `POST /api/automations/events/relatorio_pronto` | Relatórios do Dados são sob demanda; não há evento automático confiável |
| `mugo_alerta_campanha` | Dados | **Só equipe** | Disparo explícito `POST /api/automations/events/alerta_campanha` | Bloqueado para qualquer telefone que não seja da equipe |
| `mugo_resumo_diario` | CRM | Equipe | `team-daily-brief-worker`, 08h seg a sex | O CRM usa hoje `mugo_resumo_diario_equipe` |
| `mugo_tarefa_atribuida` | CRM | Equipe | `team-notification-worker` | Template vem de `MUGO_TEAM_ALERT_TEMPLATE_NAME` no CRM |
| `mugo_tarefa_prazo` | CRM | Equipe | `task-reminder-worker` | O CRM usa hoje `mugo_lembrete_tarefa` |
| `mugo_aprovacao_recebida` | CRM | Equipe | Dados → `dados-ops-events` → CRM | Já funciona assim |
| `mugo_alerta_equipe` | CRM | Equipe | `team-notification-worker` | |
| `mugo_cobranca_link_v1` | CRM | Cliente | `collection-cadence-worker` (Asaas) | O pedido citava `mugo_cobranca_link_v`; o CRM usa `_v1` |
| `mugo_pagamento_confirmado` | CRM | Cliente | `asaas-webhook` | |
| `mugo_alerta_pagamento_pendente` | CRM | Cliente | `collection-cadence-worker` / `collection-notification-worker` | |
| `mugo_solicitar_comprovante` | CRM | Cliente | CRM financeiro | |
| `mugo_aviso_renovacao_contrato` | CRM | Cliente | CRM financeiro | |
| `mugo_boas_vindas_diagnostico_v1` | CRM | Lead | CRM comercial | Marketing: exige opt-in |
| `hello_world` | Técnico | — | Nenhum | `automation_enabled = false`, não liga |

Para os templates novos do Dados, o texto aprovado não estava no repositório. A ordem das variáveis acima é a proposta, e o motor **confere a quantidade com a Meta e bloqueia** se não bater (`VARIABLES_MISMATCH`). A ordem pode ser ajustada na central.

## 4. Regras do motor (`server/services/automations.py`)

Evento → validação → destinatário → template → variáveis → fila → MugôZap (Cloud API) → webhook → histórico.

- **Modo simulado por padrão.** Sem `AUTOMATIONS_SEND_ENABLED=true`, a fila processa tudo e grava `simulado`, sem chamar o envio.
- **Bloqueios** (revalidados na hora do envio): template não aprovado na Meta, automação desligada, dono não é o Dados, variáveis em número diferente ou vazias, opt-out, Marketing sem opt-in, mensagem de equipe para telefone que não é da equipe.
- **Idempotência.** A chave junta automação, empresa, telefone, origem e o que muda de fato (ex.: horário da reunião). Enfileirar de novo é ignorado (`ON CONFLICT DO NOTHING`). O retry usa a mesma chave, e o CRM deduplica.
- **Retry com backoff**: 1 min, 5 min, 30 min, 2h, 6h. Só para falha passageira (MugôZap fora, 429, 5xx). Template recusado ou telefone inválido falha na hora.
- **Isolamento entre empresas.** Destinatário de cliente só vem de `studio_client_contacts` da mesma empresa do evento, e o enfileiramento recusa outra empresa (`TENANT_MISMATCH`). A reunião com contatos de duas empresas não gera lembrete. O relatório da resposta usa só a empresa do convite.
- **Status de entrega** (`accepted` → `sent` → `delivered` → `read`, ou `failed`) chega por `/api/hooks/crm` e nunca regride.
- **Histórico**: telefone sempre mascarado, e o token de aprovação fica cifrado na fila.

## 5. Google Calendar (`server/services/google_calendar.py`)

- OAuth com a conta corporativa: `openid email calendar.readonly`. Precisa voltar `refresh_token`.
- Sincronização **num sentido só** (Google → Dados): não existe evento duplicado por ida e volta.
- Inicial: 30 dias para trás. Incremental: `syncToken`. Se vier 410, ressincroniza do zero.
- Webhook `events.watch` validado pelo id e pelo token do canal, renovado 24h antes de expirar. O job `calendar-sync` cobre o webhook perdido (Render dormindo).
- Interna: todos os participantes são da equipe (cadastro ou `MUGO_EMAIL_DOMAIN`). Cliente: participante é contato (pelo e-mail) de exatamente uma empresa.
- Reagendou: chave nova, e o lembrete antigo é cancelado. Cancelou: tudo pendente é cancelado. Recusou: não recebe. Falta menos de 1h: sem lembrete. Marcado em cima da hora: lembrete imediato.
- Horários exibidos e gravados nas mensagens em `America/Sao_Paulo`.
- A agenda do Dados mostra "Reuniões do mês" da empresa ativa. O cliente vê só as reuniões dele, sem a lista de participantes.

## 6. Endpoints

| Método e caminho | Quem |
|---|---|
| `GET /api/automations` (situação, templates, quatro estados) | equipe |
| `PATCH /api/automations/{key}` (liga/desliga, horário, antecedência, variáveis; as do CRM não editam) | equipe |
| `POST /api/automations/catalog/sync` | equipe |
| `GET /api/automations/outbox`, `/responses`, `/usage` | equipe |
| `POST /api/automations/process` (processa a fila; simulado sem a flag) | equipe |
| `POST /api/automations/{key}/simulate` (nunca envia) | equipe |
| `POST /api/automations/events/{relatorio_pronto,alerta_campanha}` | equipe |
| `GET/POST/PATCH/DELETE /api/automations/team` e `PUT /api/automations/prefs/{phone}` | equipe |
| `GET /api/automations/google-calendar[/start, /calendars]`, `POST .../select`, `POST .../sync` | equipe |
| `GET /api/automations/google-calendar/callback` | Google (state assinado) |
| `POST /api/automations/google-calendar/webhook` | Google (token do canal) |
| `GET /api/automations/meetings` | equipe |
| `GET /api/clients/{client_id}/meetings` | membro da empresa |
| `POST /api/hooks/crm` tipo `message_status` (novo) e `invite_reply` (estendido) | CRM (chave da ponte) |

Jobs (`server/run_jobs.py`): `automations-process`, `automations-catalog-sync`, `automations-approval-reminders`, `automations-publish-check`, `calendar-sync [--full]`. **Nenhum cron foi ligado.**

## 7. Variáveis de ambiente (Render e segredo `MUGO_JOBS_ENV` do GitHub)

| Variável | Para quê |
|---|---|
| `AUTOMATIONS_SEND_ENABLED` | `true` libera envio real. Vazio = simulado |
| `WHATSAPP_WABA_ID`, `WHATSAPP_TEMPLATES_TOKEN` | Leitura dos templates (token de usuário do sistema com `whatsapp_business_management`) |
| `MUGOZAP_FUNCTION_URL`, `MUGOZAP_ANON_KEY`, `MUGOZAP_WORKER_KEY`, `MUGOZAP_TEAM_MEMBER_ID` | Já existentes (envio pelo número oficial) |
| `CRM_OPS_API_KEY` | Já existente (hook do CRM) |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | Já existentes; o mesmo app Google |
| `GOOGLE_CALENDAR_REDIRECT_URI` | `https://api.dados.mugoagencia.com.br/api/automations/google-calendar/callback` (cadastrar no Google Cloud) |
| `GOOGLE_CALENDAR_WEBHOOK_URL` | `https://api.dados.mugoagencia.com.br/api/automations/google-calendar/webhook` |
| `MUGO_AGENCY_CLIENT_ID` | Id da empresa Mugô em `clients` (padrão `mugo`) |
| `MUGO_EMAIL_DOMAIN` | Domínio dos e-mails da equipe (ex.: `mugoagencia.com.br`) |
| `AUTOMATIONS_COST_UTILITY_BRL`, `AUTOMATIONS_COST_MARKETING_BRL` | Tarifas para estimar custo na central |

## 8. Pendências fora deste repositório

1. **CRM: repassar status de entrega.** No `whatsapp-webhook`, para mensagens enviadas com `idempotency_key` começando por `auto-`, fazer POST em `DADOS_HOOK_URL` com `{"type":"message_status","status":{"provider_message_id","status","error"}}`. É o mesmo caminho e a mesma chave do `invite_reply`. Sem isso, o histórico mostra até "aceito pela Meta".
2. **Meta: templates.** Cadastrar e aprovar os templates novos do Dados (`mugo_reuniao_interna`, `mugo_reuniao_lembrete`, `mugo_ajuste_concluido`, `mugo_conteudo_publicado`, `mugo_relatorio_pronto`, `mugo_alerta_campanha`) e, se quiser os botões novos, uma versão do `mugo_convite_resumo` com "Resumo semanal", "Período completo" e "Agora não". O código já entende os botões antigos e os novos. Os templates aprovados existentes não foram alterados.
3. **Google Cloud.** Habilitar a Calendar API, adicionar o escopo `calendar.readonly` à tela de consentimento, cadastrar o redirect e verificar o domínio da API para o webhook.
4. **Contatos.** Preencher o e-mail dos contatos dos clientes (para reconhecer reuniões) e cadastrar a equipe em Automações → Equipe. Os telefones precisam existir também no CRM.

## 9. Homologação (sem mensagem real)

1. Aplicar a migração 000062 no Supabase.
2. Configurar `WHATSAPP_WABA_ID` e `WHATSAPP_TEMPLATES_TOKEN`, **sem** `AUTOMATIONS_SEND_ENABLED`.
3. Na central: **Sincronizar com a Meta** e conferir status, categoria e quantidade de variáveis de cada template.
4. **Simular** cada automação do Dados com dados de exemplo. A resposta precisa dizer "nada foi enviado".
5. Conectar o Google Calendar, escolher a agenda, criar uma reunião de teste com dois e-mails da equipe e outra com um contato de cliente. Em **Histórico** devem aparecer os lembretes agendados para 24h antes.
6. Mudar o horário da reunião de teste: o lembrete antigo fica "Cancelado" e surge um novo. Cancelar a reunião: tudo "Cancelado".
7. **Processar fila agora**: as linhas vencidas viram "Simulado" (nenhuma chamada ao MugôZap).
8. Envio controlado: ligar `AUTOMATIONS_SEND_ENABLED=true` com **só** um telefone de teste da equipe cadastrado, disparar `POST /api/automations/events/alerta_campanha` e conferir no WhatsApp e no histórico. Desligar em seguida.

## 10. Ativação em produção (precisa de autorização explícita)

1. Concluir as pendências da seção 8.
2. Definir `AUTOMATIONS_SEND_ENABLED=true` no Render e no `MUGO_JOBS_ENV`.
3. Adicionar ao `.github/workflows/sync-jobs.yml` (horários em UTC; cada expressão precisa ser única no arquivo, porque o workflow escolhe o comando pelo texto do cron):
   - `*/5 * * * *` → `automations-process`
   - `*/15 * * * *` → `calendar-sync`
   - `0 13 * * 1-5` → `automations-approval-reminders` (10h SP)
   - `55 */3 * * *` → `automations-publish-check`
   - `30 9 * * *` → `automations-catalog-sync`
4. Acompanhar por uma semana: Histórico (bloqueados e falhas), Respostas e Consumo.
