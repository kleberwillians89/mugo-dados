# QA manual — Fase 1

Status: executado localmente em Chromium/Playwright em 20/10/2026. Resultados e limitações em `docs/phase1-final-homologation.md`; evidências em `/tmp/mugo-phase1-visual-final/index.html`. Este roteiro permanece para repetição manual, não indica QA ainda não executado.

## Preparação

No checkout `/Users/k/Desktop/mugo-dados`, executar `npm run dev`. Abrir Chrome com perfil de teste, sem sessão de produção, em `http://127.0.0.1:5173/design-review.html`. O harness usa fixtures e não exige backend. Não usar a URL de produção para este roteiro. Não executar sync ou geração paga. O mock de POST retorna falha simulada; não representa atualização real bem-sucedida.

O read model agora possui transporte fictício para troca de período/releitura. Os dados disponíveis nas fixtures continuam limitados ao ano simulado. Conferir a aba Network antes de navegar: interromper se houver qualquer chamada a provider ou backend real. O harness simula `/api/` e as tabelas de read model utilizadas na revisão, e recusa fetch externo. A automação adiciona bloqueio de rede externa no contexto do navegador.

## URLs

- Meta/Dashboard: `/design-review.html?tela=meta&empresa=roove`.
- Google Ads: `/design-review.html?tela=google-ads&empresa=roove`.
- GA4: `/design-review.html?tela=ga4&empresa=roove`.
- FBITS: `/design-review.html?tela=ecommerce&empresa=vinhos`.
- Shopify: `/design-review.html?tela=ecommerce&empresa=roove`.
- Inteligência: `/design-review.html?tela=inteligencia&empresa=roove`.
- Glossário: `/design-review.html?tela=glossario`.
- Saúde dos Dados: `/design-review.html?tela=saude&empresa=roove`.

Acrescentar `&perfil=viewer` para conferir controles restritos; `&perfil=cliente` e `&perfil=agencia` para perfis autorizados. A autorização real multi-tenant é coberta pelo backend, não demonstrada por fixtures.

Cenários de canais: `&cenario=carregando`, `&cenario=erro`, `&cenario=sem-dados`, `&cenario=desconectado`. FBITS: `carregando`, `erro`, `sem-vendas`, `pendente`. Inteligência: `carregando` (3 s), `erro`, `sem-dados`, `parcial`. Estados estáticos de atualização: `&refresh=running` ou `&refresh=cooldown`. Recarregar preserva o estado da URL; conclusão automática de job/cooldown não é simulada. Não afirmar que todos os cenários de canal exercitam a mesma tela Shopify.

## Matriz mínima

Larguras CSS: **320, 360, 375, 390, 430, 768, 1024 e 1440 px**. Usar 844 px de altura no mobile e 900 px no desktop, além de testar rotação quando possível.

Em cada largura:

1. Identificar empresa/período, abrir e fechar menu; verificar navegação ativa e alvos de toque.
2. Confirmar que a página não desliza horizontalmente. No console: `document.documentElement.scrollWidth <= document.documentElement.clientWidth`. Validar visualmente também; tabelas podem rolar dentro do próprio componente. `&debug=overflow` oferece diagnóstico auxiliar do harness.
3. Conferir KPIs longos, moeda, legendas, filtros, datas e gráficos; nenhuma ação deve ficar inacessível.
4. Abrir glossário por hover/foco e toque. Conferir bordas da viewport, fórmula/fonte, Escape, clique fora e não acionamento do card.
5. Abrir menu/modal, usar Tab/Shift+Tab e Escape; conferir foco e scroll restaurados. Redimensionar menu aberto para desktop.
6. Verificar loading, erro e vazio em canais, FBITS e IA. Shopify: renderização, tabela/cartões e fonte identificada; estados adicionais precisam de fixture/teste apropriado ou ambiente autorizado, não de sync real.
7. Verificar parcial da IA explicitamente identificado e sem conclusão rejeitada. Conferir erro sem loading permanente.
8. Verificar “Atualizando dados...”/cooldown, último sucesso inalterado, viewer sem execução de mutação. Estado estático do harness não certifica concorrência distribuída.

Capturar: Dashboard desktop/mobile; IA desktop/mobile e parcial/erro; FBITS e Shopify; menu aberto; tooltip junto à borda; execução/cooldown; vazio/erro. Registrar URL, largura, altura, resultado e screenshot por caso. Capturas desta rodada disponíveis na galeria indicada acima.

## Homologação posterior autorizada

Em ambiente seguro: duas abas e duas sessões, recarregar execução real, confirmar término/cooldown no backend, troca rápida A/B/A e ausência de dados de outro tenant. Depende de autorização separada para operações de escrita; não realizar como parte deste roteiro offline. Confirmar memória/latência no Render e resultado da IA com dados autorizados, sem deduzir produção de mocks.
