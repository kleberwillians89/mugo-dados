# Aba WhatsApp

De onde vêm as conversas do número da marca, quantas viram venda e quanto custa cada venda, mais a caixa
de entrada da marca. Código: `server/services/whatsapp_insights.py`, `server/services/whatsapp_sources.py`,
`server/routes/whatsapp.py`, `src/pages/WhatsApp.tsx`.

## De onde vem o WhatsApp de cada empresa

| Empresa | Fonte | Vendas |
|---|---|---|
| Ruah (CRM próprio) | `mugoverso-bridge` do CRM da Ruah | vendas do CRM da Ruah + Shopify |
| Demais | número ligado à empresa no CRM Mugô (`dados-ops-api`) | Shopify |
| Futuro | WhatsApp nativo do MUGOVERSO (Tech Provider) | entra em `whatsapp_sources.py` |

## Configuração (Render)

```
WHATSAPP_BRAND_BRIDGES={"<client_id da Ruah no MUGOVERSO>":{"url":"https://<projeto da Ruah>.supabase.co/functions/v1/mugoverso-bridge","key":"<mesmo valor de MUGOVERSO_BRIDGE_KEY no CRM da Ruah>"}}
```

No CRM da Ruah: migration `202611100004_mugoverso_whatsapp_origin.sql`, secret `MUGOVERSO_BRIDGE_KEY`,
deploy de `whatsapp-webhook` e `mugoverso-bridge`.

## Regras

- Venda conta para a conversa quando o telefone é o mesmo e a compra acontece até 7 dias depois do
  primeiro contato. Cada venda conta uma vez. Sem telefone, não entra.
- O telefone nunca chega ao MUGOVERSO: os dois lados calculam a mesma chave (`phone_key`).
- O ID do anúncio só existe para conversas que chegaram depois da captura entrar no ar.

## Leitura da IA de atendimento (CRM da Ruah)

A atendente de IA do CRM da Ruah (Claude) mantém uma ficha de cada conversa, atualizada a cada resposta:
fase (`novo`, `interessada`, `negociando`, `comprou`, `recorrente`, `perdida`, `suporte`), interesses,
objeções (`preco`, `frete`, `prazo`, `confianca`, `pagamento`, `estoque`, `produto`, `outro`), próximo passo e resumo.

- Ponte: `conversations` traz `insight`; `leads` traz `stage` e `objections`.
- Aba: card "Onde as conversas estão" (funil por fase + "O que trava a venda"), coluna "Avançaram" e a
  objeção mais comum por anúncio, selo de fase na lista e "Leitura da IA" na lateral da conversa.
- Venda registrada vence a leitura da IA: conversa que virou venda conta como "Comprou".
- No CRM da Ruah: migração `202611100005_whatsapp_conversation_insight.sql` e deploy de
  `whatsapp-webhook` e `mugoverso-bridge`. Sem a migração, a ponte manda `insight: null` e a aba esconde o card.
