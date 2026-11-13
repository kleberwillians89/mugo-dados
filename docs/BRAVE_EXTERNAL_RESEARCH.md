# Brave Search — pesquisa externa no Mugô Dados

## Ativação

No **backend Render**, configure:

```text
EXTERNAL_RESEARCH_PROVIDER=brave
BRAVE_SEARCH_API_KEY=<secret>
```

Não use `VITE_*` nem exponha a chave no GitHub. Nenhuma migration é necessária.

O arquivo `external_research.py` resolve o adaptador por ambiente e o
`calculate_intelligence_snapshot` já consome `external_research_context`.
Quando desativado, mantém `not_configured` e não altera os dados internos.

## O que pesquisa

- Sinais públicos da marca (nome cadastrado + termos genéricos de mercado).
- Referências públicas de marketing e conteúdo.
- Resultados com `source_url` HTTPS e `researched_at` preenchidos.
- Não inventa perfis ou métricas de UGC. Criadores continuam sob Creator Intelligence.

**Limite de precisão:** Brave Search devolve resultados de pesquisa, não
certificação do conteúdo das páginas. A IA deve tratá-los como indícios com
fonte, nunca como fatos internos ou resultados comprovados. Não há leitura
profunda da página nem busca livre por instrução do usuário nesta etapa.

## Privacidade / custos

A consulta envia somente o nome público da empresa e termos genéricos.
Briefings, métricas, documentos, clientes, telefones e tokens não são enviados.
Resultados são guardados por empresa e categoria em cache de processo por 1h.
Cada cache miss faz até duas pesquisas externas por empresa (mercado/referências).
Se a Brave falhar ou limitar a consulta, a inteligência continua com as fontes
internas e sinaliza a indisponibilidade.

## Homologação

1. Executar: `PYTHONPATH=server python -m unittest server.tests.test_external_research_brave`.
2. Testar os demais testes de backend e build frontend.
3. Publicar branch após revisão e confirmar versão do Render em `/api/version`.
4. Gerar um snapshot de inteligência para empresa autorizada e confirmar
   `external_research.status=ok`, `provider=brave` e URLs públicas.
5. Desativar `EXTERNAL_RESEARCH_PROVIDER` e confirmar `not_configured`.
6. Monitorar 401/429, custos e latência no provedor antes de ampliar a coleta.

**Fora desta entrega:** motor de browsing universal em chat, enriquecimento de
criadores, scraping irrestrito, redação/publicação automática, novos dados privados.
