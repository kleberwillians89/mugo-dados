# Captura de leads por empresa — Fase 1 (não publicada)

Esta PR prepara uma entrada universal para formulários e integrações **server-to-server**.
Não altera o Shopify da Roove nem outros sites; não muda fluxos de e-mail ou WhatsApp;
não faz disparos, não inscreve leads em campanhas e não ativa sincronização automática
dos conectores existentes. A migração deve ser revisada e aplicada antes de testar a API.

## Modelo

- Fonte criada por empresa com role agency_admin ou client_admin.
- Uma chave aleatória forte por fonte, retornada apenas na criação e armazenada em SHA-256.
- Endpoint de ingestão verifica chave, tenant associado e fonte ativa.
- E-mail e telefone são criptografados antes da persistência; índices por hash.
- Evento exige `event_id` estável para idempotência, inclusive em retries.
- Alegações de consentimento por e-mail/WhatsApp são registradas separadamente,
  com `consent_verified=false`. **Nenhuma declaração recebida por webhook basta para disparar marketing.**
- O retorno administrativo de eventos traz metadados, nunca contato em claro.

## Rotas

- `GET /api/relationship/lead-sources?client_id=<tenant>` — listar fontes.
- `POST /api/relationship/lead-sources?client_id=<tenant>` — criar fonte, JSON
  `{"name":"Newsletter Roove","kind":"custom_form"}`. A chave é exibida uma única vez.
- `POST /api/relationship/lead-sources/{id}/disable?client_id=<tenant>` — bloquear chave.
- `GET /api/relationship/captured-leads?client_id=<tenant>` — auditoria sem PII.
- `POST /api/hooks/leads/{id}` com header `X-Lead-Capture-Key` e JSON:
  ```json
  {
    "event_id": "newsletter-2026-11-17-00001",
    "email": "cliente@example.com",
    "phone": "+5511999999999",
    "origin": "newsletter-footer",
    "consent": {"email": true, "whatsapp": false}
  }
  ```
  A chave **não** deve ser colocada no JavaScript do navegador: enviar sempre pelo
  backend/Edge Function da loja, com proteção antiabuso/captcha no formulário.

## Antes do deploy

1. Revisar migração `20270109_000118_lead_capture_sources.sql` (não aplicar automaticamente).
2. Executar `python -m unittest server/tests/test_lead_capture.py` com PYTHONPATH=server e suíte existente.
3. Revisar integração de permissões por módulo, segurança de rate limit e retenção/eliminação LGPD.
4. Aplicar migration em staging, testar duas empresas e bloquear chave de uma fonte.
5. Testar chave errada, mesma chave em outra fonte, evento duplicado, rejeição
   de payload inválido e reenvio após timeout.
6. Validar LGPD e opt-in por canal em fonte autenticada e verificável.
7. Só depois conectar Shopify/Wake/Meta e site da Roove; manter integrações
   atuais até comparação dos eventos sem perdas nem duplicidade.

## Próxima etapa

UI em Relacionamento > Fontes de leads; backfill e sync Shopify e Wake/FBITS;
captura de Meta Lead Ads; roteamento para perfil 360; vinculação verificável
ao consentimento e à lista; filas de automações com retry/DLQ e métricas de sucesso.
Nenhuma dessas partes é entregue nesta PR.
