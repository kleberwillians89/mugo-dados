# Mugô Dados — preparação para Meta App Review

Este documento descreve a configuração e o roteiro de revisão da integração Meta do Mugô Dados. Não inclua neste arquivo tokens, secrets ou a senha do reviewer.

## URLs oficiais

- Produto: **Mugô Dados**
- Frontend: `https://dados.mugoagencia.com.br`
- Backend: `https://api.dados.mugoagencia.com.br`
- Callback Meta: `https://api.dados.mugoagencia.com.br/api/oauth/meta/callback`
- Privacy Policy URL: `https://dados.mugoagencia.com.br/privacidade`
- Data Protection URL: `https://dados.mugoagencia.com.br/protecao-de-dados`
- Data Deletion Instructions URL: `https://dados.mugoagencia.com.br/exclusao-de-dados`

O callback deve ser cadastrado exatamente como está acima, sem barra final e usando HTTPS.

## Escopo da integração

O Mugô Dados permite que uma empresa autorize a Meta e selecione separadamente uma Página do Facebook, o Instagram profissional vinculado e uma conta Meta Ads. O backend descobre somente os ativos acessíveis pela autorização, valida a seleção e persiste as conexões no tenant da empresa. Após a seleção, a plataforma importa dados para os dashboards de Instagram orgânico, Instagram Insights e Meta Ads.

## Permissões solicitadas

### `public_profile`

- Motivo: identificar a conta Meta que concluiu a autorização.
- Endpoint Graph: `/me?fields=id,name`.
- Feature visível: nome e identificador da conta autorizada no retorno do onboarding.
- Como comprovar: conecte a Meta e observe “Conta autorizada” na etapa de seleção de ativos.

### `pages_show_list`

- Motivo: descobrir as Páginas do Facebook disponíveis para a pessoa autorizadora.
- Endpoint Graph: `/me/accounts`.
- Feature visível: lista “Páginas do Facebook” no onboarding.
- Como comprovar: após retornar da Meta, abra a lista de Páginas descobertas e selecione a Página de homologação.

### `pages_read_engagement`

- Motivo: ler a identificação da Página e localizar seu vínculo com o Instagram profissional.
- Endpoints Graph: `/me/accounts` e `/{page_id}`.
- Feature visível: nome da Página e indicação do Instagram profissional vinculado.
- Como comprovar: na seleção de ativos, escolha uma Página que mostre o Instagram profissional associado.

### `instagram_basic`

- Motivo: ler o perfil e as mídias da conta profissional selecionada.
- Endpoints Graph: `/{ig_user_id}`, `/{ig_user_id}/media` e `/{ig_user_id}/stories`.
- Feature visível: identificação do perfil, publicações, Reels e Stories nos relatórios orgânicos.
- Como comprovar: conclua a conexão, abra o dashboard Meta e navegue pelos dados orgânicos da conta selecionada.

### `instagram_manage_insights`

- Motivo: importar métricas autorizadas do perfil e do conteúdo profissional.
- Endpoints Graph: `/{ig_user_id}/insights`, `/{media_id}/insights` e `/{story_id}/insights`.
- Feature visível: alcance, visualizações, interações e demais indicadores disponíveis nos relatórios orgânicos.
- Como comprovar: no dashboard Meta, mostre os indicadores do Instagram e abra a visualização de conteúdo/Insights.

### `ads_read`

- Motivo: descobrir contas de anúncios e importar métricas de campanhas, anúncios e criativos sem criar ou alterar anúncios.
- Endpoints Graph: `/me/adaccounts`, `/{act_id}/insights`, `/{act_id}/ads` e `/{act_id}/adcreatives`.
- Feature visível: seletor de conta Meta Ads e dashboard pago com investimento e desempenho.
- Como comprovar: selecione a conta de anúncios de homologação, aguarde a sincronização e abra o dashboard Meta Ads.

### `business_management`

- Motivo: descobrir os Business Managers disponíveis durante o onboarding e ajudar a pessoa autorizadora a reconhecer o ambiente empresarial correto antes da seleção de Página, Instagram e Ads.
- Endpoint Graph: `/me/businesses`.
- Feature visível: seção **Business Managers** na tela de revisão dos ativos descobertos. Ela mostra os nomes e identificadores disponíveis ou informa claramente quando nenhum Business Manager foi retornado.
- Como comprovar: depois do retorno do OAuth, mantenha a tela de onboarding aberta e mostre a seção Business Managers antes de selecionar os demais ativos.

O `business_management` não é usado para criar, editar ou excluir ativos empresariais. Nesta entrega ele sustenta a descoberta/listagem visível no onboarding e não deve ser removido sem uma decisão de produto e nova validação do fluxo.

## Variáveis necessárias no Render

Use valores reais somente no painel seguro do Render. O Git deve conter apenas nomes e placeholders.

| Variável | Uso |
|---|---|
| `APP_ENV=production` | Ativa as proteções de ambiente de produção. |
| `META_APP_ID` | Identificador do aplicativo Meta. |
| `META_APP_SECRET` | Secret server-side usado na troca e renovação do token. |
| `META_GRAPH_VERSION` | Versão da Graph API; o código possui default `v25.0`. |
| `META_OAUTH_REDIRECT_URI` | Callback oficial exato do backend. |
| `META_LOGIN_CONFIG_ID` | ID da Login Configuration criada no Meta for Developers. |
| `OAUTH_STATE_SECRET` | Segredo canônico do state persistido; use valor aleatório com pelo menos 32 caracteres. |
| `TOKEN_ENCRYPTION_KEY` | Proteção das credenciais persistidas e fallback compatível do state. |
| `SUPABASE_URL` | URL do projeto Supabase usado pelo backend. |
| `SUPABASE_ANON_KEY` | Validação de autenticação conforme a configuração do backend. |
| `SUPABASE_SERVICE_ROLE_KEY` | Operações server-side no Supabase; nunca expor ao frontend. |
| `ALLOW_ORIGIN` | Origins permitidos; inclua o frontend oficial. |
| `FRONTEND_URL` | URL oficial do frontend para fluxos que a utilizam. |
| `CRON_SECRET` | Proteção das rotinas de sincronização. |

### Segredo de state

O fluxo atual de `/api/oauth/meta/start` cria o state por `server/services/oauth_state.py`. Ele usa `OAUTH_STATE_SECRET` como variável canônica e `TOKEN_ENCRYPTION_KEY` como fallback compatível. `META_OAUTH_STATE_SECRET` permanece no exemplo por compatibilidade com o helper interno de `server/services/meta_oauth.py`, mas não é o segredo lido pelo caminho atual de início/callback. Não renomeie nem rotacione esses valores durante uma autorização em andamento.

### Login Configuration

`META_LOGIN_CONFIG_ID` deve receber o ID da Login Configuration configurada em **Meta for Developers → Facebook Login for Business**. O backend inclui esse valor como `config_id` e envia `override_default_response_type=true` no diálogo OAuth. Não confundir esse ID com `META_APP_ID` e não versionar o valor real.

## Checklist no Meta for Developers

- [ ] Confirmar o domínio `dados.mugoagencia.com.br`.
- [ ] Incluir o domínio em App Domains.
- [ ] Cadastrar o callback exato `https://api.dados.mugoagencia.com.br/api/oauth/meta/callback`.
- [ ] Habilitar Facebook Login for Business.
- [ ] Criar ou revisar a Login Configuration.
- [ ] Copiar o `config_id` para `META_LOGIN_CONFIG_ID` no Render.
- [ ] Adicionar as sete permissões solicitadas à Login Configuration.
- [ ] Configurar Privacy Policy URL como `https://dados.mugoagencia.com.br/privacidade`.
- [ ] Configurar Data Deletion Instructions URL como `https://dados.mugoagencia.com.br/exclusao-de-dados`.
- [ ] Solicitar acesso avançado/App Review para as permissões aplicáveis.
- [ ] Concluir Business Verification quando exigido pelo painel.
- [ ] Preparar usuário de teste/reviewer.
- [ ] Preparar Página de teste acessível por esse usuário.
- [ ] Vincular um Instagram profissional à Página de teste.
- [ ] Preparar conta de anúncios com dados demonstráveis.
- [ ] Escrever justificativas individuais alinhadas às features acima.
- [ ] Gravar e anexar o vídeo da submissão.

## Credenciais e tenant do reviewer

- Reviewer email: `[preencher somente no Meta Dashboard]`
- Reviewer password: `[preencher somente no Meta Dashboard]`
- Tenant de homologação: `[preencher]`

**Nunca versionar a senha do reviewer.** Entregue a credencial exclusivamente pelos campos seguros do Meta Dashboard.

## Roteiro detalhado para o reviewer

1. Acesse `https://dados.mugoagencia.com.br`.
2. Entre com a credencial de reviewer fornecida no Meta Dashboard.
3. Abra **Integrações**.
4. Escolha a empresa de homologação informada acima.
5. Na integração Meta, clique em **Conectar com Meta**.
6. Na tela da Meta, autentique-se e autorize as permissões solicitadas.
7. Aguarde o retorno automático ao Mugô Dados.
8. Confirme a identificação da conta Meta autorizada.
9. Observe a seção Business Managers e a lista de Páginas descobertas.
10. Selecione a Página de homologação que possui Instagram profissional vinculado.
11. Selecione o Instagram profissional exibido para essa Página.
12. Selecione a conta Meta Ads de homologação.
13. Salve a conexão.
14. Aguarde a confirmação da importação/sincronização inicial.
15. Abra o dashboard Meta.
16. Demonstre o perfil, conteúdo e indicadores orgânicos/Insights do Instagram.
17. Demonstre o dashboard Meta Ads com a conta paga selecionada.

O reviewer deve enxergar a conta autorizadora, Business Managers disponíveis, Página, Instagram profissional, conta de anúncios e os dashboards correspondentes. A disponibilidade de métricas depende de dados existentes nos ativos de homologação.

## Roteiro curto para o vídeo da submissão

1. Comece na tela de login e entre com a conta de homologação.
2. Abra **Integrações** e mostre a empresa selecionada.
3. Clique em **Conectar com Meta**.
4. Grave a tela de autorização da Meta e as permissões apresentadas.
5. Mostre o retorno automático ao Mugô Dados.
6. Mostre a conta autorizada e a seção Business Managers.
7. Selecione a Página, o Instagram profissional e a conta Meta Ads.
8. Salve e aguarde a confirmação da sincronização.
9. Abra o dashboard orgânico e mostre perfil, conteúdo e Insights.
10. Abra o dashboard pago e mostre os dados de Meta Ads.

Evite exibir senhas, tokens, secrets, painéis de infraestrutura ou dados de empresas que não façam parte da homologação.

## Verificação antes da submissão

- Acesse as três páginas legais em janela anônima e confirme que não há redirecionamento para login.
- Execute os testes Meta/OAuth e os testes das rotas públicas.
- Confirme que o callback e as URLs legais publicadas correspondem exatamente às URLs deste documento.
- Faça um fluxo completo com os ativos de homologação antes de gravar o vídeo final.
- Confirme no Meta Dashboard quais permissões ainda dependem de acesso avançado ou Business Verification.
