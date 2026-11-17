# Importação de contatos dentro do MUGOVERSO

A aba **Relacionamento → WhatsApp → Disparos em massa** agora recebe a seção
**Importar contatos existentes** para a empresa selecionada.

## Ações disponíveis
- **Importar clientes da loja**: usa o conector ativo Shopify ou Wake/FBITS,
  lendo apenas `shopify_customers` / `fbits_customers` já sincronizados.
  Requer `client_admin` ou `agency_admin`.
- **Importar conversas WhatsApp**: consulta 365 dias por meio da ponte já
  configurada, criando perfis por `phone_key` quando a origem oferece essa chave.
  Alguns CRMs fornecem apenas hash, não número discável.
- **Status**: mostra contagem por origem e total no tenant, atualizados após cada importação.
- **Rascunhos**: erro informa que a migration 000120 pode estar pendente.
- Nenhum desses endpoints envia mensagens reais nem troca o tenant.

## Limites importantes
- Compras e histórico de conversas **não** são prova individual de opt-in
  WhatsApp. Importação nunca ativa disparo por si só.
- A projeção incremental de loja permanece opt-in pela variável
  `RELATIONSHIP_AUTO_PROJECT_ENABLED`. Só ligar após validar correções de
  exclusão/retificação e os contratos da origem.
- No upsert de contatos, flags de consentimento são omitidas para preservar
  as evidências já homologadas: novos contatos recebem `false` pelo DEFAULT
  do banco; contatos existentes não perdem opt-in por sobrescrita de importação.
- Importação da loja não chama Shopify nem Wake ao vivo. Se a tabela de
  origem estiver vazia, ela retornará zero, e é preciso executar o sync nativo.
- Para a Ruah, a importação das conversas aproveita identidades por hash, mas
  a ponte do CRM ainda precisa disponibilizar contatos plenamente resolvidos.
- A interface de disparo real segue bloqueada até implementar e validar
  opt-in e opt-out individualizados, destinatário discável, template e fila durável.

## Homologação da Roove (sem Terminal)
1. Aplicar migration 000119 no Supabase e 000120 para rascunhos.
2. Merge da PR e deploy de backend e frontend.
3. Selecionar **Roove** no seletor da plataforma.
4. Abrir **Relacionamento → WhatsApp → Disparos em massa**.
5. Clicar **Importar clientes da loja**; a quantidade importada deve aparecer.
6. Repetir e conferir que não duplica por identidade da origem.
7. Voltar à Ruah e verificar que o total da Roove não aparece.
8. Confirmar que o rascunho não envia mensagens e que o número elegível é 0
   até homologação específica de envio.
