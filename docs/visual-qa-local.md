# QA mínimo local — 20/10/2026

Não houve navegador disponível na CUA. Nenhuma captura ou viewport foi executado nesta rodada. Este roteiro é o aceite manual restante, não uma alegação de QA visual concluído.

## Executar no Chrome do usuário

Na raiz `/Users/k/Desktop/mugo-dados`, executar `npm run dev`. Não iniciar backend. Abrir as URLs abaixo em janela de teste, usando dados fictícios do harness. Não abrir a entrada principal com sessão de produção nem usar OAuth.

Base: `http://127.0.0.1:5173/design-review.html`.

| Área | Query |
|---|---|
| Dashboard Meta | `?tela=meta&empresa=vinhos&perfil=cliente&banner=0` |
| Google | `?tela=google-ads&empresa=roove&perfil=viewer&banner=0` |
| E-commerce FBITS | `?tela=ecommerce&empresa=vinhos&perfil=viewer&banner=0` |
| E-commerce Shopify | `?tela=ecommerce&empresa=roove&perfil=viewer&banner=0` |
| Inteligência real | `?tela=inteligencia&empresa=vinhos&perfil=viewer&banner=0` |

Executar em **1440×900** e **390×844**, pixels CSS, zoom 100%:

1. Conferir menu ativo, abertura/fechamento da gaveta, foco/Escape, seletor de empresa e período. Usar `perfil=agencia` para alternar empresas de exemplo.
2. Conferir cards, gráficos, tabelas, textos e filtros sem sobreposição ou overflow horizontal da página. `debug=overflow` é um diagnóstico auxiliar; remover antes da captura final.
3. Meta: acrescentar `&cenario=carregando`, depois `erro`, depois `sem-dados`. E-commerce FBITS: usar `carregando`, `erro`, `sem-vendas`. Não presumir que cada cenário FBITS modifica Shopify.
4. Inteligência: `cenario=carregando` demora três segundos e termina; `erro` mostra falha local; `sem-dados` mostra estado sem análise. Geração/conversa não chamam IA: devolvem falha simulada. Conferir erro amigável e saída de loading, sem apagar leitura anterior.
5. Atualização: perfil cliente com `refresh=running` mostra “Atualizando dados...” e conserva último sucesso; `refresh=cooldown` mantém botão bloqueado; sem esse parâmetro começa disponível após “Verificando acesso...”. Viewer não recebe refresh. Clique em refresh administrador retorna falha local 503, sem provider. Verificar dados anteriores preservados.
6. Último sucesso fictício `2026-10-20T12:42:00Z` deve aparecer em São Paulo como `20/10/2026 às 09`; `cenario=sem-dados` não inventa sucesso. Estados running/cooldown são fixtures estáticas; retirar o parâmetro para o estado pronto. Transições reais de conclusão/cooldown continuam cobertas pelos testes existentes, não são certificadas por essa fixture estática.

Registrar somente: URL, empresa fictícia, período, viewport, resultado e captura sanitizada. Sem credenciais ou payloads reais.

## Cobertura e limites

O harness agora renderiza Inteligência real e monta `DataHealthProvider`. Mocks novos cobrem contexto/latest/history, status Meta/Google, Saúde dos Dados, viewer 403, erro/vazio/loading. Resolução de empresa respeita caminho/header e a lista de empresas simuladas; chamadas desconhecidas `/api/` retornam 404 local. Nenhuma integração externa é chamada por esses handlers. Os mocks não entram no build de produção.

Backend não iniciado: `startup_bootstrap` pode persistir configuração se iniciado com variáveis reais. Não é necessário para este roteiro. Não houve sincronização, análise paga, migration ou deploy nesta rodada.

Não foi reproduzido defeito visual do produto. Se Chrome concluir os seis passos sem falha crítica, a pendência de aceite visual mínimo fica concluída. Se aparecer tela branca, erro de renderização ou overflow crítico, registrar evidência e corrigir somente a causa reproduzida antes de publicar.
