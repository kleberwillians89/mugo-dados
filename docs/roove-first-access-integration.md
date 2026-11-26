# Roove First Access → Mugô Dados — integração e homologação

## Situação do código
- Backend já inclui a rota `POST /api/shopify/first-access`, protegida por assinatura do Shopify App Proxy e allowlist da loja.
- O serviço `services.lead_capture.ingest` resolve o tenant pela fonte autenticada, persiste em `lead_capture_events` com PII criptografada e registra consentimento **declarado, ainda não verificado**.
- A campanha é `roove_first_access_2026`; a equipe pode consultá-la nas rotas de Relacionamento.
- **Não é criada automaticamente uma membership na tabela `relationship_list_members`**, que exige opt-in verificável. Captura e elegibilidade para disparos são etapas diferentes.
- Esta branch remove a dependência implícita de python-multipart na recepção de formulário App Proxy.

## Configuração exigida (somente backend, segredos não publicados)
1. No Shopify, confirmar se o app já tem **App Proxy** ativo em `/apps/mugo-first-access`, apontando para `https://<backend>/api/shopify/first-access`. O path definitivo deve corresponder ao app instalado.
2. No Render, definir `SHOPIFY_CLIENT_SECRET` com o segredo **do app que assina o App Proxy**, `ROOVE_FIRST_ACCESS_SHOP_DOMAIN` com o domínio **real** `.myshopify.com` da Roove.
3. No Mugô Verso, selecionar o tenant Roove e criar uma fonte em `POST /api/relationship/lead-sources`, com `name="Roove First Access BF 2026"` e `kind="shopify"`. Guardar a chave retornada uma única vez em armazenamento de segredos.
4. No Render, definir `ROOVE_FIRST_ACCESS_SOURCE_ID` e `ROOVE_FIRST_ACCESS_INGEST_KEY` com a fonte criada.
5. Verificar migrações que criam `lead_capture_sources` e `lead_capture_events` **sem reaplicar** migrações já presentes.
6. Inserir o formulário de `integrations/roove/first-access-form.liquid` **ou adaptar seus nomes de campo e script ao layout já publicado**. Não sobrescrever a landing page existente.
7. `event_id` único por tentativa; em retry com falha de rede, preservar o mesmo event_id até confirmação. Os dados devem ser enviados pelo App Proxy, nunca diretamente com a chave da fonte do backend.
8. Confirmar política de privacidade, finalidades do tratamento e consentimentos por canal. Não inferir opt-in de compra, cadastro ou participação no grupo.

## Teste controlado — necessário antes de Meta Ads
1. Criar cadastro com contato de teste autorizado, incluindo os dois opt-ins apenas se consentidos.
2. No Network do navegador, conferir `POST /apps/mugo-first-access`, resposta HTTP 2xx com `{"ok":true}`; resposta diferente não pode ser mostrada como sucesso.
3. Em Relacionamento, usar `GET /api/relationship/campaigns/roove_first_access_2026/summary` e `/recent` (autenticado, tenant Roove). O total deve aumentar na primeira inscrição. Em retry com o mesmo event_id, não deve aumentar.
4. Verificar `GET /api/relationship/captured-leads` e logs da API pelo request_id (nunca logar nome, e-mail ou telefone).
5. Testar CORS/App Proxy/Shopify, celular, duplicatas, 422, 401, falha de internet e multiempresa. Confirmar que os leads não aparecem em outra empresa.
6. Só disparar Meta Lead depois de sucesso real. Não publicar/ativar tráfego até a confirmação manual ponta a ponta.

## Limites
- A página Shopify publicada não foi alterada por este PR; requer acesso administrativo ao tema para inserir a integração visual final.
- Sem acesso às env vars Render, à loja Shopify e ao banco de produção, o diagnóstico da falha original **não está fechado**.
- Não houve envio real, merge, deploy ou migration remota.
