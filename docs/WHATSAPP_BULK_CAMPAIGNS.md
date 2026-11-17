# WhatsApp → Disparos em massa (etapa de planejamento)

A quinta aba agora está dentro da tela atual **Relacionamento → WhatsApp**, sem criar um novo módulo.

## O que funciona nesta entrega

- Lê apenas templates aprovados da WABA conectada ao tenant.
- Consulta quantidade de registros importados de Shopify, Wake/FBITS e conversas WhatsApp.
- Mostra separadamente quantos perfis têm a flag `marketing_whatsapp_verified` e quantos podem ser enviados (**zero**, bloqueio deliberado).
- Valida o status do template no servidor em cada simulação.
- Salva rascunhos por empresa, com histórico e origem selecionada.
- Nenhuma rota desta entrega chama a Meta para enviar mensagens.
- A migration 000120 cria `whatsapp_campaign_drafts`, com status restrito a `draft`.

## Por que o envio real não pode ser liberado só com o merge?

Os cadastros atuais de `relationship_contacts` têm e-mail/telefone criptografados;
os perfis derivados das conversas CRM podem ter somente uma `phone_key` irreversível.
Os importadores atuais gravam consentimentos como `false` por precaução.

Não há ainda um pipeline verificável que associe cada opt-in da origem ao indivíduo
com timestamp, texto/versão da finalidade, canal e provedor, nem pipeline de opt-out
WhatsApp, fila durável, deduplicação por destinatário/campanha e webhooks de entrega.
Confirmar genericamente que "a base tem consentimento" não substitui essas evidências.

## Para habilitar o envio real em próxima etapa

1. Construir evidência por pessoa e canal: `source`, `source_event_id`, `consent_at`, `consent_text/version`,
   finalidade e atualização por revogação; preservar as permissões durante sync incremental.
2. Resolver telefone real somente na camada backend por fonte confiável (sem hashes reversíveis);
   número não pode aparecer em logs nem APIs de prévia.
3. Deduplicar usuários entre múltiplos provedores por identificadores verificados dentro do tenant,
   aplicando opt-out global da marca, supressões e políticas Meta.
4. Fila persistente, claim transacional, idempotência, limites, tentativas e retomada;
   webhooks de status da Meta, custos e auditoria.
5. Pré-voo final, aprovação explícita por campanha, modo dry-run e envio inicial
   restrito à lista de teste autorizada da Mugô. Só depois habilitar destinatários reais.

## Homologação

- Revisar e aplicar migration `20270111_000120_whatsapp_campaign_drafts.sql` em staging.
- Conferir testes frontend/backend e executar CI.
- Navegar WhatsApp → Disparos em massa; escolher tenant, origem e template aprovado.
- Simular, conferir rascunho e garantir **zero** mensagens enviadas.
- Trocar de empresa e confirmar que rascunhos e contagens não vazam.
- Enquanto a fila e consentimentos não estiverem validados, nenhuma campanha pode enviar.
