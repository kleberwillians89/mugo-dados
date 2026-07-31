# Inteligência IA

## Separação de responsabilidades

- `/`: visão objetiva das métricas.
- `/inteligencia`: interpretação, evidências, recomendações, conversa e histórico.
- O backend calcula métricas e status de disponibilidade.
- O provedor de IA recebe somente agregados tenant-scoped e referencia evidências
  pelos identificadores das métricas calculadas.
- Abrir a página não gera uma chamada de IA. Uma nova versão só é criada por
  `POST /api/intelligence/analyses`.

## Endpoints

| Endpoint | Finalidade |
| --- | --- |
| `GET /api/intelligence/context` | Métricas, fontes, qualidade e cruzamentos calculados |
| `GET /api/intelligence/latest` | Última versão salva para empresa e período |
| `POST /api/intelligence/analyses` | Criar uma nova versão explicitamente |
| `GET /api/intelligence/history` | Histórico imutável da empresa |
| `POST /api/intelligence/ask` | Pergunta vinculada a empresa, usuário e período |
| `GET /api/intelligence/conversations/{id}/messages` | Mensagens da conversa do mesmo usuário/tenant |

Todas as rotas exigem autenticação e resolvem `client_id` pelas dependências
tenant-safe. O backend filtra conversas por `conversation_id + client_id + user_id`.

## Persistência

A migration `20260802_000021_intelligence_workspace.sql` cria:

- `ai_analyses`;
- `ai_conversations`;
- `ai_messages`.

As tabelas não concedem acesso direto a `anon` ou `authenticated`. O backend usa
`service_role`, depois de validar autenticação e tenant. Análises não são
sobrescritas: atualizar cria outra linha e preserva o snapshot anterior.

## Configuração

- `OPENAI_API_KEY`: chave exclusiva do backend.
- `OPENAI_MODEL`: opcional; o padrão atual é `gpt-4.1-mini`.

Sem chave, a API salva `configuration_pending`, mantém as métricas calculadas
visíveis e não produz texto que simule uma resposta de IA.
