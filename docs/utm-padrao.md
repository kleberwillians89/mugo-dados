# Padrão de UTM da Mugô

A tabela "Vendas por origem" só liga uma venda a uma campanha quando o link do anúncio tem UTM.
Sem UTM, a venda vai para "Origem não identificada", e o sistema não distribui essa venda entre campanhas.
Este padrão vale para todas as contas que a Mugô opera.

## Regras

- Tudo em minúsculas, sem acento e sem espaço. Use `_` para separar palavras.
- `utm_campaign` = o nome da campanha na plataforma, no mesmo formato. Assim a venda da loja cruza com o gasto da campanha.
- Não coloque e-mail, telefone ou nome de cliente em nenhum parâmetro.

## Parâmetros por canal

| Canal | utm_source | utm_medium | utm_campaign | utm_content |
| --- | --- | --- | --- | --- |
| Meta Ads (Facebook/Instagram) | `{{site_source_name}}` (vira `fb` ou `ig`) | `paid_social` | `{{campaign.name}}` | `{{ad.name}}` |
| Google Ads (Search/PMax/Shopping) | `google` | `cpc` | `{campaignid}` ou o nome da campanha | `{creative}` |
| Instagram orgânico (bio, stories) | `instagram` | `social` | nome da ação (ex.: `lancamento_inverno`) | `bio`, `stories`, `post` |
| E-mail marketing | `email` ou nome da ferramenta | `email` | nome do disparo | bloco/link |
| WhatsApp / SMS | `whatsapp` ou `sms` | `messaging` | nome do disparo | — |
| Influenciadores e parceiros | nome do parceiro | `afiliado` | nome da ação | — |

Exemplo Meta Ads, no campo "Parâmetros de URL" do anúncio:

```
utm_source={{site_source_name}}&utm_medium=paid_social&utm_campaign={{campaign.name}}&utm_content={{ad.name}}
```

## Como o Mugô Dados classifica

| Canal na tela | Regra |
| --- | --- |
| Mídia paga · redes sociais | source de rede social (facebook, fb, ig, instagram, tiktok…) e medium pago (`cpc`, `paid_social`, `paid`…) |
| Mídia paga · busca | source de busca (google, bing) e medium pago |
| Redes sociais (orgânico) | source de rede social sem medium pago, ou referência de rede social sem UTM |
| Busca orgânica | referência de buscador sem UTM, ou source de busca com medium orgânico |
| E-mail · SMS/WhatsApp · Afiliados | pelo medium ou source |
| Marketplace | origem do pedido na loja (ex.: Mercado Livre na FBITS) |
| Origem não identificada | sem UTM, sem referência externa e sem origem registrada pela loja |

Modelo de atribuição: último clique com UTM que a loja registrou no pedido.
A receita é a da loja (Shopify ou FBITS), não a receita atribuída pelo Meta ou pelo Google.

## Onde a origem é lida

- **Shopify:** `landing_site` (UTMs da URL de entrada), `note_attributes` e `referring_site` do pedido. Os pedidos já gravados são preenchidos com `python3 server/run_jobs.py attribution-backfill --client-id <empresa>`, sem chamar a Shopify.
- **FBITS/Wake:** `metadados` (chave/valor), `origemPedido`/`subOrigem`, `canalOrigem` e `usuario.origemContato` de `GET /pedidos`. O campo exato onde a Wake expõe as UTMs ainda precisa ser confirmado com um pedido real; depois disso, rodar o histórico da FBITS de novo preenche os 90 dias.
