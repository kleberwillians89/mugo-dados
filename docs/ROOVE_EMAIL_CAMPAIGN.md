# Roove — campanha de e-mail pelo Relacionamento

O módulo de E-mail Marketing **já consulta** os clientes existentes da Shopify diretamente de `shopify_customers`, sem necessidade de CSV nem de outra importação. Esta PR adiciona no painel **Relacionamento → E-mail marketing → Listas** um resumo dos cadastros e da audiência de e-mail com opt-in Shopify confirmado.

## Contagens mostradas
- Cadastros com e-mail na origem.
- Contatos com aceitação de marketing registrada pela Shopify.
- Contatos elegíveis após supressões e duplicidade.

A seção usa o endpoint `POST /api/email/audience` que já existe e pode ser atualizada manualmente.

## Processo de campanha da Roove
1. Selecionar **Roove** na plataforma.
2. **Relacionamento → E-mail marketing → Listas**: verificar audiência e consentimentos.
3. **Remetente**: conferir Resend, domínio verificado e `EMAIL_SEND_ENABLED`.
4. **Campanhas**: criar, revisar e gerar teste para caixa controlada.
5. Verificar pré-validação e número de destinatários antes de autorizar agendamento real.

## WhatsApp não é automaticamente liberado
Template aprovado **não significa gratuito**, nem comprova opt-in. A aba existente de WhatsApp só suporta rascunho e simulação, pois ainda faltam evidência de consentimento por telefone, fila durável, supressões e resolução de número discável. Nenhuma campanha real é iniciada por esta PR.
