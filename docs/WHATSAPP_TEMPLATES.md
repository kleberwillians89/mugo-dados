# Templates de WhatsApp do Studio (MugôZap)

Mensagens enviadas pelo Mugô Dados através do WhatsApp oficial da Mugô (MugôZap, no CRM).
O Dados **não envia sozinho**: ele chama o `mugozap-api` do CRM, que confere se o template está
aprovado, se o telefone está cadastrado no CRM, aplica a idempotência e grava o histórico.

São 7 templates. Os textos abaixo são **exatamente** os que o código usa (`server/services/studio_messages.py`).
Se a Meta pedir mudança no texto, altere nos dois lugares.

## Como cadastrar (Kleber)

1. No **WhatsApp Manager → Modelos de mensagem → Criar modelo**, cadastre cada template abaixo com
   o **mesmo nome**, idioma **Português (BR) – `pt_BR`** e a categoria indicada.
2. Na variável do botão, use a URL base do painel: `https://<FRONTEND_URL>/aprovar/{{1}}`
   (o mesmo domínio que está em `FRONTEND_URL` no Render).
3. Depois de aprovados, no CRM: **Conversas → Templates → Sincronizar**.
4. No Render (serviço da API do Dados), configure:
   - `MUGOZAP_FUNCTION_URL` = `https://<projeto-do-crm>.supabase.co/functions/v1/mugozap-api`
   - `MUGOZAP_ANON_KEY` = a anon key do projeto Supabase do CRM
   - `MUGOZAP_WORKER_KEY` = o mesmo valor de `TASK_COMMAND_WORKER_KEY` da função no CRM
   - `MUGOZAP_TEAM_MEMBER_ID` = o id de um membro ativo da equipe no CRM, vinculado a um perfil
     **admin ou manager** (crie um membro "Mugô Dados" para o histórico ficar claro)
   - `FRONTEND_URL` = o endereço do painel (usado no botão "Ver e aprovar")
5. Cadastre os contatos do cliente **também no CRM** (cliente ou contato de WhatsApp). O CRM recusa
   telefone que não conhece; no Dados aparece "Esse telefone não está cadastrado no CRM".

Sem as variáveis do passo 4, o Dados continua funcionando: gera o link `wa.me` com o mesmo texto
para a equipe enviar manualmente.

> Regras da Meta já respeitadas: nenhuma variável no começo ou no fim do texto, nenhuma variável
> encostada em outra, sem quebra de linha dentro de variável. As frases de destaque e atenção são
> geradas a partir dos números da conta (até 140 caracteres) e podem ser editadas antes do envio.

---

## 1. `mugo_conteudo_aprovacao` — Utilidade

Usado ao enviar pautas para o cliente aprovar quando nenhuma pauta tem arte de imagem.

**Corpo**
```
Olá, {{1}}! A equipe Mugô preparou {{2}} conteúdo(s) de {{3}} para a {{4}}. Toque no botão abaixo para ver as artes e aprovar ou pedir ajuste em cada um. O link vale até {{5}} e não precisa de login.
```
**Botão** (URL dinâmica): texto `Ver e aprovar` · URL `https://<FRONTEND_URL>/aprovar/{{1}}`

**Exemplos para a Meta:** {{1}} Ana · {{2}} 12 · {{3}} novembro · {{4}} Ruah Parfums · {{5}} 18/11 · botão `kq3V9x...`

## 2. `mugo_conteudo_aprovacao_arte` — Utilidade

Mesmo envio, com a primeira arte (imagem) como cabeçalho.

**Cabeçalho:** Imagem (exemplo: qualquer arte 1080×1350)

**Corpo**
```
Olá, {{1}}! A equipe Mugô preparou {{2}} conteúdo(s) de {{3}} para a {{4}}. Esta é uma das artes. Toque no botão abaixo para ver todas e aprovar ou pedir ajuste. O link vale até {{5}} e não precisa de login.
```
**Botão** (URL dinâmica): texto `Ver e aprovar` · URL `https://<FRONTEND_URL>/aprovar/{{1}}`

## 3. `mugo_lembrete_aprovacao` — Utilidade

Lembrete de um pedido que ainda tem pautas sem resposta (reenvia o **mesmo** link).

**Corpo**
```
Olá, {{1}}! Ainda faltam {{2}} conteúdo(s) da {{3}} esperando sua aprovação. Para manter o calendário em dia, responda até {{4}} pelo botão abaixo.
```
**Botão** (URL dinâmica): texto `Ver e aprovar` · URL `https://<FRONTEND_URL>/aprovar/{{1}}`

**Exemplos:** Ana · 3 · Ruah Parfums · 18/11

## 4. `mugo_agenda_semana` — Utilidade

Agenda das publicações aprovadas da semana.

**Corpo**
```
Olá, {{1}}! Agenda de conteúdo da {{2}} para a semana de {{3}}: {{4}} publicação(ões) aprovada(s). Destaque: {{5}}. Qualquer ajuste, é só responder esta mensagem.
```
**Exemplos:** Ana · Ruah Parfums · 10/11 a 16/11 · 4 · Reels do lançamento da linha Oud (12/11)

## 5. `mugo_relatorio_trafego` — Utilidade

Resumo semanal de mídia paga (últimos 7 dias fechados). Investimento, faturamento e retorno vêm do
painel (soma de Meta Ads e Google Ads; faturamento da loja; retorno = faturamento ÷ investimento).

**Corpo**
```
Olá, {{1}}! Resumo do tráfego pago da {{2}} em {{3}}: investimento de {{4}}, faturamento da loja de {{5}} no mesmo período e retorno de {{6}} para cada R$ 1 investido. Destaque: {{7}}. Os detalhes estão no painel Mugô Dados.
```
**Exemplos:** Ana · Ruah Parfums · 03/11 a 09/11 · R$ 2.350,00 · R$ 14.820,00 · R$ 6,31 · a campanha Remarketing Oud teve o melhor retorno da semana

## 6. `mugo_resumo_semanal` — Utilidade

Enviado **toda sexta às 10h15** (job `studio-weekly-digest` no GitHub Actions) para cada contato do cliente que
recebe "tráfego pago". Os números vêm do painel (últimos 7 dias fechados). O "aprendizado" e o "próximo passo" saem da memória
semanal de cada campanha (`studio_campaign_learnings`): campanha nova, saturação, melhora, escala que funcionou.

**Corpo**
```
Olá, {{1}}! Resumo da semana da {{2}} ({{3}}): investimento de {{4}} em mídia, faturamento da loja de {{5}} e retorno de {{6}} para cada R$ 1 investido. O que aprendemos: {{7}}. Próximo passo: {{8}}. Qualquer dúvida, é só responder esta mensagem.
```
**Exemplos:** Ana · Curavino · 23/10 a 29/10 · R$ 1.250,00 · R$ 9.800,00 · R$ 7,84 · a campanha nova de catálogo no Meta trouxe 12 vendas na primeira semana · subir 20% a verba do Search Marca

> Enquanto o MugôZap não estiver configurado (ou o cliente não tiver contato cadastrado), o job grava o aprendizado e
> registra a mensagem como **aguardando**, sem enviar nada. Quando o WhatsApp for ligado e os números cadastrados,
> a mensagem passa a sair sozinha na sexta seguinte. Para o job enviar, as variáveis `MUGOZAP_*` precisam estar também
> no segredo `MUGO_JOBS_ENV` do GitHub (além do Render).

## 7. `mugo_resultados_mes` — Utilidade

Fechamento do mês anterior.

**Corpo**
```
Olá, {{1}}! Fechamos {{2}} da {{3}}: faturamento de {{4}} ({{5}} em relação ao mês anterior), {{6}} pedidos e {{7}} investidos em mídia. Ponto de atenção: {{8}}. Vamos conversar sobre os próximos passos?
```
**Exemplos:** Ana · outubro · Ruah Parfums · R$ 58.400,00 · +12,4% · 312 · R$ 9.800,00 · a taxa de conversão do site caiu 0,4 ponto

---

## Categoria

Todos são **Utilidade**: são comunicações sobre um serviço contratado (aprovação de conteúdo,
agenda e relatórios), sem oferta. Se a Meta reclassificar algum como Marketing, o envio continua
funcionando, mas com outro preço por conversa.
