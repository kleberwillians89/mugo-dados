# Operação administrativa de backfill FBITS

Curavino: Customer 360 com 168 clientes, `fbits_customers` com duas identidades
completas, conforme diagnóstico read-only informado. Render Free sem Shell:
a operação deve usar as credenciais já provisionadas no backend. Não é preciso
copiar service-role key ou token FBITS para o computador do operador.

## Contrato

POST `/api/platform/fbits/customer-identities/backfill` no backend que já serve
as chamadas `/api/platform` da aplicação. Router administrativo existente.
Authorization: Bearer da sessão autenticada de um platform admin real.
Não basta agency_admin/client_admin/viewer; não usa o tenant implícito do menu.

Body obrigatório (nenhum outro campo é aceito):

```json
{
  "client_id": "239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94",
  "confirm_client_id": "239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94"
}
```

A confirmação deve ser idêntica ao UUID informado. Sem opção global. Empresa
precisa existir antes de chamar `backfill_customer_identities`. Nenhum secret
FBITS/Supabase é recebido no corpo. O backend resolve conexão/token do tenant.

HTTP 200 retorna SOMENTE as cinco contagens do serviço:
`orders_processed`, `identities_found`, `identities_persisted`,
`identities_without_contact`, `errors` (zero em sucesso).
Contagens por página, não clientes únicos. Campos extras jamais são repassados.

401: sem autenticação válida; 403: sem platform_admin;
400: tenant/confirmacão/campos inválidos; 404: empresa inexistente;
409: lock do sync FBITS ocupado; 429: cooldown conhecido;
504: timeout; 502: falha de consulta/API/persistência/contrato.
Erro operacional retorna `detail.code` fixo e contagens quando disponíveis,
sem mensagem externa/traceback/PII. Falhas não retornam HTTP 200.

## Execução futura em produção — não executada nesta rodada

1. Após revisão e publicação por responsável autorizado, entrar na aplicação
   com uma sessão válida de platform_admin. Usar um cliente HTTP autenticado
   com essa sessão, apontando para o mesmo backend das chamadas da aplicação.
2. Enviar UMA requisição POST com o body acima, Content-Type application/json
   e Authorization da sessão. Não copiar service-role key ou token FBITS;
   não inserir secrets no body nem compartilhar o bearer em logs/chat.
3. Aguardar a resposta. A rota é síncrona e reutiliza o backfill, seu timeout
   de 25 minutos e o lock FBITS existente de 30 minutos. Não há fila/processo
   background ou garantia de conclusão após queda/restart/desconexão.
4. Se a conexão HTTP for encerrada antes da resposta, o resultado é
   indeterminado: consultar logs `[fbits][customer_backfill]` e contagens antes
   de repetir. Não presumir sucesso. Uma tentativa concorrente é bloqueada
   pelo lock. A reexecução é idempotente, mas não iniciar tentativas em loop.
5. Verificar a contagem final de identidades e contatos por tenant, somente
   leitura. Recarregar `/clientes` e conferir listagem e detalhe autenticados.
   Não prometer 168 contatos: depende dos IDs/contatos realmente disponíveis.

Operação preserva pedidos, métricas, schema, Shopify, Customer 360, frontend e
normalização/identidade existentes. O ajuste do serviço somente classifica
falhas públicas (incluindo lock/timeout) para o transporte HTTP; CLI existente
continua interrompendo com saída não zero. Não remove guards ou relaxa permissões.
