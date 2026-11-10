# Aba WhatsApp

De onde vêm as conversas do número da marca, quantas viram venda e quanto custa cada venda, mais a caixa
de entrada da marca. Código: `server/services/whatsapp_insights.py`, `server/services/whatsapp_sources.py`,
`server/routes/whatsapp.py`, `src/pages/WhatsApp.tsx`.

## De onde vem o WhatsApp de cada empresa

| Empresa | Fonte | Vendas |
|---|---|---|
| Ruah (CRM próprio) | `mugoverso-bridge` do CRM da Ruah | vendas do CRM da Ruah + Shopify |
| Clientes novos | número ligado direto no MUGOVERSO (app da Mugô na Meta) | Shopify |
| Mugô | número no CRM Mugô (`dados-ops-api`) | — |

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

## WhatsApp nativo (clientes novos)

O app da Mugô na Meta manda TODAS as mensagens para a função `whatsapp-webhook` do Supabase do MUGOVERSO.
Ela grava as dos números cadastrados no MUGOVERSO e repassa, sem alterar, as dos outros números (hoje o da
Mugô) para o webhook do CRM Mugô. O CRM confere a mesma assinatura e ignora o que não é dele.

Ligar uma vez:
1. Migration `20261208_000087_whatsapp_native.sql` no Supabase do MUGOVERSO.
2. Secrets da função (Supabase do MUGOVERSO):
   - `WHATSAPP_APP_SECRET` = App Secret do app da Mugô (o mesmo que o CRM Mugô usa)
   - `WHATSAPP_VERIFY_TOKEN` = um texto qualquer, o mesmo que vai na Meta
   - `WHATSAPP_FORWARD_URL` = `https://hdyjuyhiybjqvxsukmbn.supabase.co/functions/v1/whatsapp-webhook`
3. `supabase functions deploy whatsapp-webhook --no-verify-jwt --project-ref <projeto do MUGOVERSO>`
4. Meta → app da Mugô → WhatsApp → Configuração → Webhook: URL de retorno
   `https://<projeto do MUGOVERSO>.supabase.co/functions/v1/whatsapp-webhook`, token = `WHATSAPP_VERIFY_TOKEN`,
   campo `messages` assinado.

Cada número novo: aba WhatsApp da empresa → "Ligar número" (só agência) → ID da WABA, ID do número e o
token do usuário do sistema do BM da Mugô. O MUGOVERSO confere na Meta e assina o app na WABA.

Um número fica preso à empresa em que foi ligado (mesmo desligado), para as conversas nunca aparecerem em
outra empresa.
