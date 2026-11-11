# Mugô Radar — Ativação (v1)

## O que já funciona sem novas credenciais
- A aba `/radar` preserva as telas Meta, Google, Ecommerce, Inteligência, Clipping e Criadores.
- Clipping e temas usam os endpoints existentes do cliente autenticado.
- O backend `GET /api/clients/{client_id}/radar/overview` retorna assuntos públicos do Google Trends Brasil e os criadores **vinculados à empresa selecionada**.
- O feed público do Trends é armazenado em cache por 15 minutos por processo. Um feed indisponível não produz resultados fictícios.
- Nenhuma métrica de conversão do Pixel pode ser atribuída a concorrentes.

## Credenciais adicionais (backend, nunca frontend)
1. **YouTube Data API v3**: no Google Cloud Console, habilite a API e crie uma chave restringida à YouTube Data API. Configure `YOUTUBE_API_KEY` no ambiente do **backend**. A chave já é lida em `services/creators_providers.py`; consultas de criadores são feitas pela tela Criadores. A chave não é obrigatória para carregar o Radar v1.
2. **Apify**: se optar por discovery pago, configure `APIFY_TOKEN` no **backend** e valide os termos de cada fonte e actor. Use `CREATORS_APIFY_MONTHLY_BUDGET_USD` com teto pequeno e monitore uso na aba Criadores. Apify não é necessária para o Radar v1.
3. **Instagram Business Discovery**: usa a conexão OAuth Meta de cada empresa; verifique permissões e validade no módulo Integrações. Não copie tokens do cliente para variáveis globais.

## Validação antes do merge
- `npm run typecheck`
- `npm run test:frontend`
- `npm run test:backend`
- `npm run build`
- Entrar como Roove e confirmar Clipping, Radar e Criadores exibindo apenas dados da Roove.
- Trocar de empresa sem atualizar o navegador e confirmar ausência de referências privadas da empresa anterior.
- Conferir os links de evidência e o estado vazio sem fontes externas.
- Confirmar deploy preview Vercel e backend antes do merge.

## Limites explícitos
- A seção Demand Intelligence usa Trends Brasil, **não** é demanda específica da empresa.
- A seção Territory Intelligence lista criadores vinculados; ela **não** infere comunidades/afinidades automaticamente.
- A seção Brand Intelligence usa registros existentes do Clipping; ela **não** revela vendas ou alcance privado de concorrentes.
- Share of Attention fica desabilitado até existir coleta periódica com metodologias comparáveis por marca e plataforma.
- Configurar uma chave não ativa automaticamente uma varredura: coleta automática, histórico por período, watchlists de concorrentes e cálculo de attention são próximos incrementos, não parte deste PR.

## Segurança
Nunca comitar chaves, enviá-las por chat ou usar `VITE_*` para tokens de backend. Toda consulta autenticada passa pela resolução de tenant; URLs públicas não ampliam acesso a conteúdo interno.
