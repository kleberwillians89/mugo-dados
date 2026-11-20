# RUAH Black Friday 2026 — captação sem App Proxy Shopify

## Fluxo
Landing Shopify (nome, e-mail e WhatsApp) → POST `/api/public/ruah-bf/leads` → validação Cloudflare Turnstile → fonte RUAH autenticada **somente no backend** → `lead_capture_events` → resposta `{ok:true, accepted:true}` → botão de convite do grupo.

Campanha fixa `ruah_black_friday_2026`. Eventos recebem `utm_source`, `utm_medium` e `utm_campaign` (até 100 caracteres). Não são ativados envios, automações, listas aptas ou confirmação de entrada no grupo. Aceites de marketing são declarações não verificadas.

## Antes de ativar
1. Confirmar tenant RUAH real e migrations de captura já aplicadas; **não reaplicar em produção sem autorização**.
2. No Mugô Verso, com tenant RUAH, criar uma fonte do tipo `custom_form` chamada `RUAH Black Friday 2026`. Guardar `id` e `ingest_key` exibida uma única vez. Não colocar em Liquid, no Shopify nem no GitHub.
3. No Cloudflare Turnstile, criar widget para **ruahparfums.com.br** e **www.ruahparfums.com.br**. Guardar site key (pública) e secret key (privada). A ação esperada é `ruah_bf_signup`.
4. Configurar **somente no Render**:
   - `RUAH_BF_CLIENT_ID`: ID real da empresa RUAH no Mugô Verso.
   - `RUAH_BF_SOURCE_ID`: UUID da fonte do tenant.
   - `RUAH_BF_INGEST_KEY`: chave secreta retornada na criação da fonte.
   - `RUAH_BF_TURNSTILE_SECRET`: segredo Turnstile.
5. Implantar backend em staging antes de qualquer deploy de produção, verificando registro `POST /api/public/ruah-bf/leads`, CORS para a loja e ausência de redirecionamentos.
6. No editor de tema da Shopify, substituir a seção `ruah-black-friday-countdown.liquid` pela versão desta entrega, manter a URL HTTPS exata do backend e preencher **Turnstile Site Key**. O tema não precisa de aplicativo Shopify nem de App Proxy.
7. Testar com dado sintético consentido em ambiente isolado: origem inválida (403), Turnstile ausente (422), fonte/tenant incompatível (503), válido (200 JSON), evento repetido (200 `duplicate:true`), tela de erro, redirecionamento ao grupo **apenas após sucesso**. Conferir contagem em Relacionamento → Captação na empresa RUAH.
8. Configurar rate limit adicional por IP em edge/WAF (Cloudflare); o Turnstile é verificação anti-bot, **não substitui** limites distribuídos. Não publicar tráfego até teste de carga básico e revisão LGPD.

## Observações
- O `Origin` HTTP é conferido para impedir chamadas originadas de outros sites em navegadores, mas **não constitui autenticação**. O backend verifica token Turnstile com hostname e action e valida a chave da fonte server-side.
- Configurar política de privacidade, retenção, supressão e exercício dos direitos do titular antes da campanha; participação em grupo e consentimento para mensagens individuais são diferentes.
- A proteção por senha da Shopify não impede envio cross-origin à API desde que o domínio da loja carregue a página e as regras CORS estejam corretas.
- O botão abre o convite; **não confirma a entrada no grupo**.
- Confirmar domínio oficial do backend em produção. Endpoint padrão do Liquid pode precisar ajuste conforme instalação real.
- Não subir secrets, contatos reais ou capturas de rede com informações pessoais no PR.
- Sem deploy, sem migrations remotas e sem envios neste PR.
