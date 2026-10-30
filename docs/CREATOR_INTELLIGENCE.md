# Creator Intelligence (MVP 1)

Descoberta, análise, comparação e shortlists de criadores UGC e influenciadores.
Menu **Operação → Criadores** (`/criadores`).

## Quem vê o quê

| Perfil | Vê | Pode |
|---|---|---|
| Agência/plataforma | Banco inteiro, custos Apify/YouTube | Tudo, inclusive descoberta por hashtag e TikTok (Apify) |
| client_admin | Só criadores e shortlists da própria empresa | Analisar @ (Instagram/YouTube), sugestões com IA, shortlists |
| viewer | Só criadores e shortlists da própria empresa | Somente leitura |

"Criadores da empresa" são os consultados para ela (`creator_client_links`, migração 000061):
análise de @, descoberta, sugestão da IA ou inclusão em shortlist.

## Fontes

| Fonte | Uso | Custo | Configuração |
|---|---|---|---|
| Meta Business Discovery | Analisar um @ do Instagram (conta Business/Criador) e enriquecer resultados de hashtag | Grátis; limite por empresa (token Meta da própria empresa) | Nenhuma: usa a conexão Instagram já feita em Integrações |
| YouTube Data API v3 | Analisar canal por @ (3 unidades) e buscar canais (101 unidades) | Grátis até a cota diária | `YOUTUBE_API_KEY` |
| Apify | Descoberta por hashtag (Instagram) e TikTok (perfil e hashtag) | Créditos; teto mensal interno | `APIFY_TOKEN`, Actors opcionais |

Contas pessoais do Instagram não aparecem na Business Discovery: ficam sem seguidores
e são sinalizadas em `missing_fields`.

## Sugestões com IA

`POST /suggest` usa o contexto de negócio da empresa (Empresas → editar) e o briefing opcional
para a IA (mesma `OPENAI_API_KEY`/`OPENAI_MODEL` da Inteligência) indicar @ do Instagram.
Cada @ é conferido na Meta Business Discovery: só volta conta real e profissional, com métricas
oficiais; o resto aparece em `discarded`. A IA nunca fornece números.

## Variáveis (server/.env)

- `YOUTUBE_API_KEY`
- `APIFY_TOKEN`
- `APIFY_INSTAGRAM_HASHTAG_ACTOR` (padrão `apify~instagram-hashtag-scraper`)
- `APIFY_TIKTOK_ACTOR` (padrão `clockworks~tiktok-scraper`)
- `CREATORS_APIFY_MONTHLY_BUDGET_USD` (padrão 5): ao atingir, novas pesquisas Apify retornam 402
- `CREATORS_APIFY_ESTIMATED_RUN_USD` (padrão 0,25): reserva mínima por execução e valor contabilizado quando a Apify não informa o custo
- `CREATORS_YOUTUBE_DAILY_UNITS` (padrão 9000)
- `CREATORS_CACHE_HOURS` (padrão 24): perfis mais novos que isso não são consultados de novo

## Banco

Migração `20261111_000060_creator_intelligence.sql` (aplicação manual, aditiva):
`creators`, `creator_metrics` (snapshots), `creator_shortlists`, `creator_shortlist_items`,
`creator_api_usage`. Criadores são públicos e compartilhados; shortlists têm `client_id`.

## Engajamento

- Instagram: (média de curtidas + média de comentários) ÷ seguidores × 100, últimos 12 posts.
- YouTube/TikTok: (curtidas + comentários) ÷ visualizações × 100, nos vídeos com os três dados.
- Curtidas ocultas, seguidores ausentes etc. ficam `null` e entram em `missing_fields`.

## Endpoints (`/api/clients/{client_id}/creators`)

`GET /` catálogo · `POST /lookup` · `POST /search` · `GET /{id}` · `POST /{id}/refresh` ·
`POST /compare` · `POST /suggest` · `GET /usage` · `GET|POST /shortlists` · `GET|DELETE /shortlists/{id}` ·
`POST /shortlists/{id}/items` · `PATCH|DELETE /shortlists/{id}/items/{item_id}`

## Próximas etapas (fora deste MVP)

Match Score (pesos UGC/influência do documento), briefings, campanhas UGC, marcações/hashtag
via Meta (exige permissões extras na App Review) e cruzamento com vendas por cupom/UTM.
