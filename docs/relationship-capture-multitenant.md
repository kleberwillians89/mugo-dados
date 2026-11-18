# Captação reutilizável — Shopify → Mugô Verso (sem variáveis por cliente)

## O que foi implementado nesta branch
- Mantém a rota antiga `POST /api/shopify/first-access` para compatibilidade.
- Nova rota `POST /api/shopify/lead-capture` recebe formulário `application/x-www-form-urlencoded` pelo **Shopify App Proxy assinado**.
- Valida assinatura e timestamp da Shopify usando o segredo do **aplicativo**, já mantido no backend como `SHOPIFY_CLIENT_SECRET`.
- Encontra a loja instalada em `shopify_stores`, exige `status=active` e descobre o `client_id` **no servidor**.
- Cria fonte Shopify padrão isolada por tenant no primeiro cadastro (UUID determinístico evita duplicação por concorrência) ou reutiliza fonte existente.
- Persiste em `lead_capture_events` com criptografia, deduplicação por `event_id` e `campaign_key`; continua **sem ativar envios** nem presumir opt-in.
- A aba existente `E-mail marketing > Captação` oferece escolha de campanha, URL UTM, fontes e métricas por tenant, sem novo módulo.

## Ativação inicial da Roove (uma vez)
1. No app Shopify instalado na Roove, configurar **App Proxy**:
   - Subpath público da loja: `/apps/mugo-first-access`
   - Destino da API: `https://<seu-backend-render>/api/shopify/lead-capture`
   - Confirmar assinaturas com `SHOPIFY_CLIENT_SECRET` **do mesmo app**. Não mudar segredo se houver outros fluxos dependentes.
2. Na landing page, editar a seção Roove First Access:
   - `capture_mode = app_proxy`
   - `app_proxy_path = /apps/mugo-first-access`
   - `<input type=hidden name=campaign>` deve aceitar o query param seguro `mugo_campaign` do link rastreável.
   - Enviar via `fetch` com `Content-Type: application/x-www-form-urlencoded`, corpo `new URLSearchParams(new FormData(form))`.
   - Confirmar `ok===true && accepted!==false` antes de mostrar sucesso, disparar Pixel Lead ou ir ao grupo.
3. Não é necessário configurar `ROOVE_FIRST_ACCESS_SOURCE_ID` ou `ROOVE_FIRST_ACCESS_INGEST_KEY` **para a rota genérica**; estas variáveis são **somente da rota antiga** e não precisam ser removidas.
4. Confirmar que a Roove existe em `shopify_stores` como loja ativa, vinculada à empresa correta. Outras lojas precisam ser instaladas/conectadas pelo app Shopify antes de captar.
5. Publicar frontend + backend da branch **apenas após revisão** e executar cadastro controlado.
6. Conferir em `E-mail marketing > Captação`, selecionando `roove_first_access_2026` e comparando com `lead_capture_events`.

## Próximas campanhas
1. Selecionar empresa ativa > E-mail marketing > Captação.
2. Informar identificador (ex.: `summer_2027`) e URL da landing, copiar link ou parâmetros Meta.
3. A landing deve aceitar `mugo_campaign`, enviar `campaign` e `event_id` estável por tentativa.
4. Após o primeiro lead confirmado, a campanha aparece na seleção de histórico. **Este MVP não possui catálogo persistente de rascunhos**.
5. Usar a mesma fonte Shopify para qualquer campanha daquele tenant. Fontes externas não-Shopify ainda usam segredo server-to-server, gerado uma vez via painel.
6. O rastreamento persistido hoje cobre `utm_source`, `utm_medium` e `utm_campaign`. Identificadores por anúncio/posicionamento ainda exigem evolução aditiva de schema/backend. Não prometer atribuição individual sem essa etapa.

## Gate para tráfego
- Um envio assinado retorna `ok:true` e é mostrado em Captação na empresa correta.
- Outra loja assinada não consegue enviar para o tenant Roove.
- Loja inativa ou desconhecida retorna 403.
- Repetir `event_id` não duplica o evento.
- Honey-pot retorna `accepted:false` e não conta conversão.
- Captura não dá permissão de envio marketing; consentimentos permanecem declarados e pendentes de verificação.
- Pixel/CAPI não são disparados por este backend. Configurar e testar o evento Lead na landing depois da confirmação; deduplicar se usar ambos.
- Nunca enviar mensagens reais, aplicar migrations remotas ou fazer deploy sem autorização.

## Limites de homologação
Código alterado em branch isolada. Não houve alteração no Liquid **publicado**, no Shopify Dev Dashboard, no Render ou nas variáveis de produção. Testes unitários foram adicionados, mas execução/CI e teste real ponta a ponta ainda precisam ser confirmados antes do merge.
