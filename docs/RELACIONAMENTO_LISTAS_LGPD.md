# Relacionamento — listas e campanhas (guia LGPD)

## Escopo
Listas, segmentação e pré-envio ficam dentro de Relacionamento > E-mail Marketing > Listas e Campanhas. Não existe um CRM paralelo.
A base guarda identificadores pseudonimizados (hashes), metadados e eventos técnicos. O e-mail em claro é lido da loja conectada no momento da conferência ou do envio.

## Regras de segurança
1. Marketing exige opt-in verificável na fonte. Na Shopify, o estado atual subscribed prevalece sobre a flag antiga accepts_marketing; revogação bloqueia envio. FBITS não informa consentimento: campanhas promocionais ficam sem destinatários elegíveis.
2. Importar não concede autorização. Só entram contatos da base conectada com aceite válido e sem supressão; rejeitados são contados sem retornar dados pessoais.
3. A fila volta a conferir consentimento, existência na base e descadastros antes de cada lote. Mantém idempotência e descadastro em um clique.
4. O pré-envio valida lista, contagem, remetente e assunto; público vazio é bloqueado no servidor.
5. Todas as consultas de listas e histórico são filtradas pela empresa e protegidas por autenticação/papel. Trocar de empresa limpa informações visíveis na UI.
6. O titular pode ser removido da lista, e a lista pode ser excluída. Solicitações de correção ou exclusão na fonte devem chegar ao controlador da marca e ao sistema de e-commerce conectado.
7. Esta entrega não usa a lista de e-mails como autorização para WhatsApp ou Instagram. WhatsApp marketing exige opt-in específico e template aprovado; Instagram Direct continua limitado aos usos e janelas autorizados pela Meta.

## Homologação antes do merge/deploy
1. Rodar testes backend e frontend/build; revisar alterações contra a branch main atual.
2. Aplicar manualmente e uma única vez a migration supabase/migrations/20270107_000116_relationship_audiences.sql depois de conferir o schema 000108–000115 no ambiente.
3. Manter EMAIL_SEND_ENABLED=false e WHATSAPP_MARKETING_SEND_ENABLED=false em homologação.
4. Importar um contato Shopify subscribed, um unsubscribed e um inexistente: somente o primeiro pode entrar.
5. Validar prévia, teste, público vazio, agendamento simulado, cancelamento, mudança de empresa, descadastro, histórico e remoção de membro.
6. Só habilitar envio real após conferir remetente, domínio, webhooks, evidências de consentimento e aprovação operacional da marca.

## Limites LGPD
Essas proteções técnicas não substituem base legal documentada, transparência, política de privacidade, contrato controlador-operador, prazos de retenção, medidas de segurança, gestão de incidentes nem revisão jurídica. O código não executa expurgo automático completo de todo o histórico.
Não afirmar conformidade legal integral sem avaliação do controlador e da assessoria jurídica.