# Roove First Access — captura e análise no Relacionamento

## Objetivo

Landing Shopify coleta **nome, e-mail e WhatsApp**, com consentimentos opcionais e independentes para e-mail e WhatsApp. Mugô Dados registra cada cadastro em `lead_capture_events` com identificação da campanha `roove_first_access_2026`, deduplicação por `event_id`, nome/dados de contato criptografados e UTMs. A aba **Relacionamento → E-mail Marketing → Captação** apresenta totais, leads únicos, declarações de aceite por canal, pendentes de validação, volume diário, origem e registros recentes com dados sensíveis mascarados.

**Não há envio, inscrição automática em lista elegível nem WhatsApp disparado por esta integração.** Uma declaração recebida do formulário não vira opt-in validado. As tabelas possuem RLS e acesso somente pelo backend service-role.

## Implantação controlada, sem mexer na produção automaticamente

1. Fazer revisão e merge do PR após testes backend/TS/build. Aplicar manualmente e **apenas com autorização**, no banco e projeto correto, `supabase/migrations/20270120_000130_roove_first_access_tracking.sql`. Revisar previamente todas as migrations anteriores (inclusive a base de captura 000118).
2. No Mugô Dados com a **empresa Roove** ativa, criar uma fonte pelo endpoint autenticado `POST /api/relationship/lead-sources` com payload `{"name":"Roove First Access 26/11","kind":"shopify"}`. Guardar o `id` e a `ingest_key` retornada uma única vez.
3. Configurar SOMENTE no backend Render, com acesso restrito:
   - `ROOVE_FIRST_ACCESS_SOURCE_ID`: UUID da fonte criada;
   - `ROOVE_FIRST_ACCESS_INGEST_KEY`: chave da fonte (nunca no tema Shopify);
   - `ROOVE_FIRST_ACCESS_SHOP_DOMAIN`: domínio real `loja.myshopify.com` da Roove;
   - `SHOPIFY_CLIENT_SECRET`: segredo já existente **do MESMO aplicativo Shopify** configurado para o App Proxy.
4. No aplicativo Shopify que tem esse segredo, configurar **App Proxy** do caminho `/apps/mugo-first-access` apontando por HTTPS para `https://api.dados.mugoagencia.com.br/api/shopify/first-access`. Não presumir que um app personalizado antigo já possui App Proxy habilitado.
5. No arquivo Liquid versão V3 da landing, ativar `App Proxy conectado ao Mugô Verso` e preencher o caminho `/apps/mugo-first-access` SOMENTE após checar os quatro itens anteriores.
6. Homologar primeiro com dados fictícios autorizados: rejeição de assinatura incorreta; rejeição de outra loja; timestamp antigo; campos inválidos; cadastro válido; duplicação pelo mesmo `event_id`; troca de empresa; contagens e UTMs; checar ausência de envio. Confirmar que a resposta da Shopify retorna JSON com `{"ok":true}`.
7. Validar no painel **Captação**, sem disparar nenhuma mensagem real. Limpar dados sintéticos somente com autorização explícita.

## Limitações e LGPD

- O painel conta eventos recebidos e pessoas deduplicadas por hash de e-mail (ou telefone quando não há e-mail). Retentativas com `event_id` igual não geram novos eventos. O painel NÃO mede visitas, cliques no link de grupo ou taxa de conversão da página; essas métricas exigem eventos adicionais.
- `consent_email_claimed` e `consent_whatsapp_claimed` são **declarações ainda não verificadas**; nunca tratar como audiência apta para disparo.
- Não há atualização automática de assinatura de marketing na Shopify, nem inclusão automática nas listas de `relationship_list_members`. Essa ponte deve ser ativada apenas após validar a origem e a base legal, conciliar opt-out e supressões.
- O App Proxy comprova assinatura e loja no momento da solicitação; ele não comprova que foi uma pessoa real nem que a pessoa autorizou um canal. Exigir controles antispam, política de privacidade, retenção e canal de revogação na operação.
- Credenciais nunca no Liquid, GitHub, eventos do navegador, URLs ou logs.
