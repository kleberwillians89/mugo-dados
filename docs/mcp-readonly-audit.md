# PR A — MCP de leitura e isolamento

Candidato local: `feat/mcp-readonly-tools`, `/tmp/mugo-mcp-tools-checkout`.
Base: `badcb97a3b29af366ab351019056d57d0adffc4e` (`origin/main` local).
Não foi criado commit, push, PR ou deploy. Nenhum ambiente remoto foi alterado.

## O que muda

SDK oficial `mcp==1.30.0`, Streamable HTTP stateless, respostas JSON em `/mcp`.
Dez ferramentas: `list_companies`, `get_data_freshness`, `get_business_overview`,
`get_paid_media`, `get_site_traffic`, `get_sales_by_origin`, `get_customer_summary`,
`get_goals`, `get_business_context`, `get_latest_analysis`.
Todas declaram `readOnlyHint`, sem sincronização, geração de IA ou escrita de negócio.
GET/HEAD recebem 405; não há stream SSE persistente. O protocolo permite GET 405
quando o servidor não oferece SSE. Inicialização e chamadas foram testadas pelo SDK real.

Reutiliza snapshot canônico sem pesquisa externa/detalhes de compradores, leitores Meta/Google Ads,
construtores numéricos GA4, atribuição de vendas, metas e contexto existentes.
GA4 consulta somente projeções necessárias, com tetos de 401 fatos diários e 2.001 fatos por dimensão;
usa os construtores existentes de resumo/canal. Não chama o relatório GA4 completo, cujo leitor
pode materializar até 200.000 fatos por tabela. Excesso de dimensão omite o detalhamento integralmente,
sem apresentar soma truncada. Máximo de 50 campanhas/canais/landing pages/metas na resposta.

## Segurança

- `MCP_ENABLED` desligado por padrão; SDK importado apenas quando habilitado.
- Nesta entrega NÃO existe autenticação de produção: produção recebe 404, mesmo com bypass ligado.
- Desenvolvimento exige `APP_ENV=development` (ou local/dev/test), `ALLOW_NO_AUTH=true`, peer e listener locais.
  Qualquer marcador production/prod, ou `RENDER=true`, fecha o bypass.
- `DEV_USER_ID` é configuração local; nunca vem de argumentos do modelo.
- A cada chamada, `require_user_client_access(..., fresh=True)` mantém a união de permissões existente.
  `is_platform_admin(..., fresh=True)` ignora o cache global de 60 segundos apenas quando solicitado.
  Os demais consumidores mantêm o comportamento anterior. A listagem também pode ser limitada e fresca.
- Piloto opcional por `MCP_PILOT_CLIENT_IDS`; vazio permite apenas empresas já autorizadas.
- Nenhum argumento aceita usuário, credenciais, conexão, SQL ou conta de anúncios.
- Projeções/whitelists numéricas; sem linhas de compradores, raw, nomes de campanhas, UTM livre ou URLs.
  Referências externas são HMAC com chave efêmera por operação, descartada ao terminar; não permitem ligação entre consultas.
- Usuário autorizou expressamente omitir contexto/análise livres sem comprovação de origem agregada segura.
  A disponibilidade e os períodos são devolvidos, com explicação da omissão. Não se tenta adivinhar nomes por regex.
- Limites: 60 requisições/min por identidade local, até 2 leituras concorrentes, autorização 8 s,
  leitura 20 s, argumentos HTTP até 32 KiB, JSON lógico até 64 KiB e resposta HTTP até 256 KiB.
- O SDK tem logs minimizados; o transporte Supabase redige corpo/mensagem de erro somente no contexto MCP.
  A instrumentação dos demais endpoints permanece no comportamento anterior.

## Limitações funcionais explícitas

- Transporte aceita intervalo de até 400 dias, mas snapshot canônico existente suporta até 366.
  Acima disso, informa a limitação; não recorta datas nem soma métricas incompatíveis.
- Total histórico de compradores, taxa de recompra e ticket por grupo ficam nulos quando não há agregado
  canônico disponível sem materializar compradores. Novos/recorrentes/ticket geral usam os indicadores existentes.
- Não há criação de agregados novos, alteração de regra de KPI ou classificação de texto livre como seguro.
- Esta entrega NÃO conecta Claude remoto; depende do PR B.
- A validação do texto produzido pelo Claude externo não é executada por estas tools. Os validadores do `/ask` não mudaram.

## Como testar

Ambiente utilizado: `/tmp/mugo-mcp-venv`, dependências de teste + SDK fixado.

```sh
PYTHONPATH=server:server/tests /tmp/mugo-mcp-venv/bin/python -m unittest test_mcp_readonly
PYTHONPATH=server:server/tests /tmp/mugo-mcp-venv/bin/python -m unittest discover -s server/tests
npm run typecheck
npx eslint src
npx vitest run
npm run build
git diff --check
```

Testes novos cobrem todas as tools contra outro tenant, membership removida, administradores,
seis IDs genéricos, conta/conexão/período Google Ads, GA4 minimizado, PII plantada, leitura sem escrita,
limites, erros seguros, protocolo, anotação read-only e troca de identidade no transporte real.

Frontend sem alterações: 748 testes passaram, typecheck, eslint e build com exit 0.
PR A: 16 testes novos passaram. Backend completo: 1.705 executados, 1.702 aprovados e as três falhas da base.
A execução backend completa mantém somente as três falhas preexistentes, reproduzidas também
em cópia limpa da base (54 testes nos dois módulos):

1. `test_progressive_context.ProgressiveContextTests.test_complete_orders_allow_calculable_zero_or_positive_recurrence`
2. `test_progressive_context.ProgressiveContextTests.test_uncovered_period_does_not_turn_known_historical_customers_into_zero`
3. `test_viewer_release_readiness.EveryMutationRouteHasARoleGuardTests.test_no_mutation_route_lacks_a_role_guard`

As duas primeiras esperam 5 consultas onde a base realiza 6. A terceira aponta as quatro rotas
preexistentes de mutação de conversas. Nenhuma foi alterada ou dispensada nesta entrega.

## Migration e conexão no Claude

Este PR não contém SQL novo. Não habilitar em produção nem cadastrar este candidato local no Claude.
O passo a passo remoto e a migration 045 pertencem exclusivamente ao PR B.

## Referências verificadas

- https://claude.com/docs/connectors/building/authentication — discovery, DCR e callback oficial.
- https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/v1.30.0/README.md — linha v1 em manutenção de segurança;
  v2 é a linha principal. O pin v1 evita trocar a arquitetura de transporte nesta entrega.

O grafo Graphify existente orientou a localização dos serviços; as decisões foram confirmadas nos arquivos reais.
Nenhum grafo, arquivo temporário ou alteração paralela deve entrar no pacote.

## Publicação e rollback

Preparar PR A → main; PR B depende integralmente de A. Solicitar autorização antes de commit;
as regras locais proíbem push. Desligar `MCP_ENABLED` fecha a superfície MCP. Nenhuma migration no rollback de A.
GO para revisão local com limitações registradas; NO-GO para habilitação em produção nesta entrega isolada.
