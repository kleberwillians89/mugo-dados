# Templates de WhatsApp do Studio (MugôZap)

Mensagens enviadas pelo Mugoverso através do WhatsApp oficial da Mugô (MugôZap, no CRM).
O Dados **não envia sozinho**: ele chama o `mugozap-api` do CRM, que confere se o template está
aprovado, se o telefone está cadastrado no CRM, aplica a idempotência e grava o histórico.

São 8 templates. Os textos abaixo são **exatamente** os que o código usa (`server/services/studio_messages.py`).
Se a Meta pedir mudança no texto, altere nos dois lugares.

## Como cadastrar (Kleber)

1. No **WhatsApp Manager → Modelos de mensagem → Criar modelo**, cadastre cada template abaixo com
   o **mesmo nome**, idioma **Português (BR) – `pt_BR`** e a categoria indicada. **Tipo de variável: Nome**
   (`{{nome}}`, `{{marca}}`…), exatamente como no texto. Só o botão de URL continua com `{{1}}`.
2. Na variável do botão, use a URL base do painel: `https://<FRONTEND_URL>/aprovar/{{1}}`
   (o mesmo domínio que está em `FRONTEND_URL` no Render).
3. Depois de aprovados, no CRM: **Conversas → Templates → Sincronizar**.
4. No Render (serviço da API do Dados), configure:
   - `MUGOZAP_FUNCTION_URL` = `https://<projeto-do-crm>.supabase.co/functions/v1/mugozap-api`
   - `MUGOZAP_ANON_KEY` = a anon key do projeto Supabase do CRM
   - `MUGOZAP_WORKER_KEY` = o mesmo valor de `TASK_COMMAND_WORKER_KEY` da função no CRM
   - `MUGOZAP_TEAM_MEMBER_ID` = o id de um membro ativo da equipe no CRM, vinculado a um perfil
     **admin ou manager** (crie um membro "Mugoverso" para o histórico ficar claro)
   - `FRONTEND_URL` = o endereço do painel (usado no botão "Ver e aprovar")
5. Cadastre os contatos do cliente **também no CRM** (cliente ou contato de WhatsApp). O CRM recusa
   telefone que não conhece; no Dados aparece "Esse telefone não está cadastrado no CRM".

Sem as variáveis do passo 4, o Dados continua funcionando: gera o link `wa.me` com o mesmo texto
para a equipe enviar manualmente.

> **Dados sempre reais:** o faturamento vem do indicador oficial da loja; quando ele não existe (ex.: Fbits sem
> KPI oficial), vem dos pedidos da página **Origem das vendas**. Sem faturamento em nenhuma das duas, a mensagem
> **não é montada** (nunca sai "—" ou retorno R$ 0,00). A frase de destaque cita venda ou pedido de verdade, sem
> travessão e sem ponto final duplicado.

> Regras da Meta já respeitadas: nenhuma variável no começo ou no fim do texto, nenhuma variável
> encostada em outra, sem quebra de linha dentro de variável. As frases de destaque e atenção são
> geradas a partir dos números da conta (até 140 caracteres) e podem ser editadas antes do envio.

---

## 1. `mugo_conteudo_aprovacao` — Utilidade

Usado ao enviar pautas para o cliente aprovar quando nenhuma pauta tem arte de imagem.

**Corpo**
```
Olá, {{nome}}! A equipe Mugô preparou {{quantidade}} conteúdo(s) de {{mes}} para a {{marca}}. Toque no botão abaixo para ver as artes e aprovar ou pedir ajuste em cada um. O link vale até {{validade}} e não precisa de login.
```
**Botão** (URL dinâmica): texto `Ver e aprovar` · URL `https://<FRONTEND_URL>/aprovar/{{1}}`

**Exemplos para a Meta:** nome Ana · quantidade 12 · mes novembro · marca Ruah Parfums · validade 18/11 · botão `kq3V9x...`

## 2. `mugo_conteudo_aprovacao_arte` — Utilidade

Mesmo envio, com a primeira arte (imagem) como cabeçalho.

**Cabeçalho:** Imagem (exemplo: qualquer arte 1080×1350)

**Corpo**
```
Olá, {{nome}}! A equipe Mugô preparou {{quantidade}} conteúdo(s) de {{mes}} para a {{marca}}. Esta é uma das artes. Toque no botão abaixo para ver todas e aprovar ou pedir ajuste. O link vale até {{validade}} e não precisa de login.
```
**Botão** (URL dinâmica): texto `Ver e aprovar` · URL `https://<FRONTEND_URL>/aprovar/{{1}}`

## 3. `mugo_lembrete_aprovacao` — Utilidade

Lembrete de um pedido que ainda tem pautas sem resposta (reenvia o **mesmo** link).

**Corpo**
```
Olá, {{nome}}! Ainda faltam {{pendentes}} conteúdo(s) da {{marca}} esperando sua aprovação. Para manter o calendário em dia, responda até {{validade}} pelo botão abaixo.
```
**Botão** (URL dinâmica): texto `Ver e aprovar` · URL `https://<FRONTEND_URL>/aprovar/{{1}}`

**Exemplos:** Ana · 3 · Ruah Parfums · 18/11

## 4. `mugo_agenda_semana` — Utilidade

Agenda das publicações aprovadas da semana.

**Corpo**
```
Olá, {{nome}}! Agenda de conteúdo da {{marca}} para a semana de {{semana}}: {{quantidade}} publicação(ões) aprovada(s). Destaque: {{destaque}}. Qualquer ajuste, é só responder esta mensagem.
```
**Exemplos:** Ana · Ruah Parfums · 10/11 a 16/11 · 4 · Reels do lançamento da linha Oud (12/11)

## 5. `mugo_relatorio_trafego` — Utilidade

Resumo semanal de mídia paga (últimos 7 dias fechados). Investimento, faturamento e retorno vêm do
painel (soma de Meta Ads e Google Ads; faturamento da loja; retorno = faturamento ÷ investimento).

**Corpo**
```
Olá, {{nome}}! Resumo do tráfego pago da {{marca}} em {{periodo}}: investimento de {{investimento}}, faturamento da loja de {{receita}} no mesmo período e retorno de {{roas}} para cada R$ 1 investido. Destaque: {{destaque}}. Os detalhes estão no Mugoverso.
```
**Exemplos:** Ana · Ruah Parfums · 03/11 a 09/11 · R$ 2.350,00 · R$ 14.820,00 · R$ 6,31 · a campanha Remarketing Oud teve o melhor retorno da semana

## 6. `mugo_resumo_semanal` — Utilidade

> **Desde que o WhatsApp oficial (MUGOZAP_*) está ligado, a sexta manda primeiro o `mugo_convite_resumo`**
> ("Quer receber aqui?"). Se o cliente tocar em "Sim, quero ver", este resumo sai na hora como **texto livre**
> (a resposta do cliente abre a janela de 24h). Este template continua cadastrado para o envio direto pela tela
> (Aprovação → Mensagens → Resumo semanal).

Enviado **toda sexta às 10h15** (job `studio-weekly-digest` no GitHub Actions) para cada contato do cliente que
recebe "tráfego pago". Os números vêm do painel (últimos 7 dias fechados). O "aprendizado" e o "próximo passo" saem da memória
semanal de cada campanha (`studio_campaign_learnings`): campanha nova, saturação, melhora, escala que funcionou.

**Corpo**
```
Olá, {{nome}}! Resumo da semana da {{marca}} ({{periodo}}): investimento de {{investimento}} em mídia, faturamento da loja de {{receita}} e retorno de {{roas}} para cada R$ 1 investido. O que aprendemos: {{destaque}}. Próximo passo: {{proximo}}. Qualquer dúvida, é só responder esta mensagem.
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
Olá, {{nome}}! Fechamos {{mes}} da {{marca}}: faturamento de {{faturamento}} ({{variacao}} em relação ao mês anterior), {{pedidos}} pedidos e {{investimento}} investidos em mídia. Ponto de atenção: {{atencao}}. Vamos conversar sobre os próximos passos?
```
**Exemplos:** Ana · outubro · Ruah Parfums · R$ 58.400,00 · +12,4% · 312 · R$ 9.800,00 · a taxa de conversão do site caiu 0,4 ponto

## 8. `mugo_convite_resumo` — Utilidade

Pergunta se o cliente quer receber o resumo. **Botões de resposta rápida** (cadastrados no template, sem variável):
`Sim, quero ver` e `Agora não`. Quando o cliente toca em **Sim**, o CRM avisa o Dados e o relatório de tráfego dos
últimos 7 dias sai na hora, em texto livre (o clique abre a janela de 24h, então não precisa de outro template).
**Agora não** recebe só um "combinado". Antes de perguntar, o Dados monta o relatório: se faltar dado, a equipe fica
sabendo na hora e o cliente nunca recebe um "sim" sem resposta.

**Corpo**
```
Olá, {{nome}}! O resumo da {{marca}} de {{periodo}} está pronto, com investimento em mídia, vendas da loja e o destaque da semana. Quer receber aqui no WhatsApp?
```
**Botões** (resposta rápida): `Sim, quero ver` · `Agora não`

**Exemplos:** Nasser · Curavino · 23/10 a 29/10

> Precisa: `DADOS_HOOK_URL` = `https://mugo-dados.onrender.com/api/hooks/crm` nos segredos do CRM e a mesma
> `DADOS_OPS_API_KEY`/`CRM_OPS_API_KEY` nos dois lados.

---

## Categoria

Todos são **Utilidade**: são comunicações sobre um serviço contratado (aprovação de conteúdo,
agenda e relatórios), sem oferta. Se a Meta reclassificar algum como Marketing, o envio continua
funcionando, mas com outro preço por conversa.
