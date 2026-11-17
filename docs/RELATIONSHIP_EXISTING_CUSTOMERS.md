# Relacionamento — usar a base que já existe (fase 1)

Os cadastros dos clientes **não** começam do zero. A operação abaixo copia,
por tenant, os clientes já persistidos em `shopify_customers` ou `fbits_customers`
para a projeção privada `relationship_contacts`. A fonte continua intacta.

## Regras e limites

- Importação explícita por empresa (agency_admin/client_admin), sem operação global cega.
- Inclui cadastros Shopify mesmo sem pedidos. Wake/FBITS usa os contatos persistidos;
  se a integração só tiver pedidos e não tiver completado o backfill de identidade,
  a importação terá cobertura parcial e **não deve ser tratada como completa**.
- Mesma identidade da origem atualiza o mesmo registro via upsert, sem duplicar.
- Nenhuma campanha é habilitada. Compra/cadastro **não** significam permissão
  de e-mail ou WhatsApp; os dois campos de elegibilidade ficam falsos.
- Nome/e-mail/telefone criptografados; isolamento por `client_id`.
- Se não houver comércio conectado, a rota devolve 409 em vez de fingir sucesso.
- Limite inicial 20 mil por empresa, falha fechada se ultrapassar.
- Não exclui clientes removidos na origem; a política de exclusão/retificação
  precisa ser alinhada antes de usar a projeção em produção.

## Rotas

Com `Authorization: Bearer <token>` e `X-Client-Id: <id>`:

- `POST /api/relationship/contacts/sync` — importa cadastros já sincronizados.
- `GET /api/relationship/contacts/status` — contagem e origem, sem PII.

## Por empresa

- Roove/Shopify: aproveita `shopify_customers` e webhooks já existentes.
- Curavino/Wake-FBITS: aproveita `fbits_customers` após backfill da origem.
- Ruah: CRM próprio via `mugoverso-bridge` atualmente expõe vendas e conversas
  com chaves de telefone, **não uma exportação completa e autorizada de clientes**.
  É necessário ampliar o contrato da ponte do CRM antes do backfill.
- Mugô: usa CRM da organização; não existe garantia de que o dado esteja na
  tabela de comércio. Exige adaptador CRM com autenticação e permissão.
- Outros tenants: resolução pelo conector realmente ativo, nunca pelo nome.

## Fase 2 — obrigatória para promessa de sincronização automática

Executar projeções incrementais depois do sync Shopify e Wake/FBITS, com
paginação e checkpoint; integrar CRM da Ruah/Mugô; receber `lead_capture_events`
sem tratar todo evento como pessoa nova; deduplicar por identificadores verificados;
UI na área Relacionamento; revalidar permissões, consentimentos, exclusões e
supressões. Não desligar automações existentes antes da homologação ponta a ponta.

## Homologação

1. Aplicar migration 000119 em staging após revisão.
2. Executar testes `server/tests/test_relationship_contacts.py` e suíte backend.
3. Fazer POST para apenas 1 tenant e comparar contagens com Customer 360.
4. Repetir POST e conferir que a contagem não cresce por duplicação.
5. Trocar tenant e conferir isolamento, sem acesso a dados externos.
6. Validar perfis sem pedidos, sem e-mail, e com opt-out.
7. Conferir logs sem dados pessoais.
