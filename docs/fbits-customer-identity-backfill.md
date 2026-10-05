# Backfill de identidades FBITS — operação manual de um tenant

Diagnóstico de produção informado em 05/10/2026: Curavino tem 168 clientes
no Customer 360, mas apenas duas linhas em `fbits_customers`, ambas completas.
Isto confirma incompletude da persistência de identidades; não determina quando
ou por que os demais pedidos foram sincronizados sem essas linhas.

O histórico inicial existente lê `/pedidos` por `DataPedido`, em janelas de
sete dias. O sync incremental usa `DataAlteracao` e marcador menos duas horas.
Reiniciar o sync completo também regravaria pedidos e métricas. Esta operação
reutiliza `plan_windows`, `FbitsClient.iter_order_pages`, `normalize_customer`,
`normalize_customers` e `_persist_customer_identities`, sem alterar os pedidos,
métricas financeiras ou marcadores de histórico/incremental.

## Executar futuramente

Não executado nesta rodada. Em ambiente backend controlado, com as variáveis
já provisionadas pelo runtime e a versão revisada do código disponível, a partir
da raiz do repositório:

```sh
python3 server/scripts/backfill_fbits_customers.py \
  --client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 \
  --confirm-client-id 239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94 \
  --apply
```

Não existe endpoint novo, execução automática ou opção para todos os tenants.
Requer UUID válido, confirmação igual, conexão FBITS ativa e token do próprio
tenant. Usa o mesmo lock da sincronização FBITS e timeout de 25 minutos, antes
do lease de 30 minutos expirar. Não executar junto com sync FBITS.

O intervalo é determinado pela menor e maior `order_date` dos `fbits_orders`
do tenant; cobre dias completos. Não assume que os últimos 90 dias ainda
contenham todos os pedidos históricos. Sem datas persistidas, interrompe.

Grava somente `fbits_customers` usando chave `(client_id, fbits_customer_id)`.
Perfis sem external ID ou sem qualquer contato não são criados. Nome nunca é
chave. Contatos existentes não vazios prevalecem sobre dados históricos;
campos vazios podem ser preenchidos. O modo conservador é exclusivo do backfill:
a política do sync normal permanece intacta. Nenhum payload bruto é persistido.

## Observabilidade e retomada

O resumo `[fbits][customer_backfill]` registra:
- `orders_processed`: pedidos recebidos;
- `identities_found`: identidades com external ID, distintas dentro de cada página;
- `identities_persisted`: linhas submetidas com sucesso ao upsert, por página;
- `identities_without_contact`: identidades da página sem nome/e-mail/telefone;
- `errors`: falha que interrompeu a operação.

Contagens de identidade NÃO são clientes únicos do histórico: o mesmo cliente
pode aparecer em páginas/janelas diferentes. Para verificar cobertura, usar a
contagem final da tabela por tenant, somente leitura. Logs HTTP existentes
continuam registrando apenas endpoint, janela, status e quantidade, sem PII.

Falhas de API, tabela, token ou timeout interrompem com saída não zero e erro
público sem traceback/payload. Páginas anteriores podem já estar persistidas;
reexecutar o mesmo comando é seguro e não duplica identidades. Não marca sucesso
quando persistência falha. Não cria/aplica migration.

## Aceite para Curavino

Esperamos mais que as duas identidades atuais, conforme os IDs e contatos
realmente retornados pela origem no período persistido. Não prometemos 168.
Após a operação, comparar contagens de campos preenchidos da tabela e verificar
uma resposta autenticada de `GET /api/customers` e `GET /api/customers/{id}` para
Curavino. Recarregar `/clientes` para descartar o cache de sessão da listagem.
Conferir contatos, isolamento e manutenção das métricas. Não considerar produção
resolvida apenas pelo resumo do comando ou pelos testes locais.
