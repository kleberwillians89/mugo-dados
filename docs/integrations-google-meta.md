# Integrações Google e Meta

## Fonte da verdade

- Google usa `integration_connections`, com credenciais separadas por produto:
  `provider=ga4` e `provider=google_ads`. Escopos de um produto não tornam a
  conexão do outro produto elegível.
- Meta continua usando `meta_connections` como fonte operacional de tokens,
  ativos, cron e sincronização. `integration_connections` é uma projeção segura
  para o onboarding e para o estado da autorização.

Essa compatibilidade é intencional. Remover `meta_connections` agora quebraria
os jobs e os vínculos de ativos existentes.

## Migração Meta planejada

1. Adicionar identificadores estáveis entre a autorização em
   `integration_connections` e cada ativo em `meta_connections`.
2. Fazer backfill tenant-scoped, sem copiar tokens em texto aberto.
3. Mover leitura e renovação de credenciais para um único serviço baseado em
   `integration_connections`; manter ativos selecionados em tabela própria.
4. Migrar cron e sync para o novo resolvedor e comparar resultados em paralelo.
5. Só após validação e rollback testado, descontinuar colunas de token legadas.

Nenhuma etapa acima deve remover RLS, memberships ou tabelas existentes.

## Conexões antigas

Conexões Google anteriores à separação por provider devem ser reconectadas se o
provider não corresponder ao produto ou se o escopo exigido não estiver em
`scopes`. Para GA4, o registro deve ter `client_id` correto, `provider=ga4`,
estado utilizável e `https://www.googleapis.com/auth/analytics.readonly`.

Conexões Meta só precisam de reconexão quando a validação indicar token expirado
ou revogado, permissão removida, ou ativo que deixou de estar disponível. A
ausência de Instagram ou de conta de anúncios é cobertura parcial, não invalida
automaticamente os outros produtos Meta.
