# WhatsApp Roove — Meta App proprio no Mugô Dados

## Implementado

O webhook existente do Mugô Dados agora aceita aplicativos Meta independentes pelo seletor `?meta_app_id=<APP_ID>`.

- **Legado (sem seletor):** usa `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` e preserva `WHATSAPP_FORWARD_URL` (repasse exclusivo de números desconhecidos do app legado ao CRM).
- **Roove:** `?meta_app_id=1161210926623351` usa `META_APP_1161210926623351_WEBHOOK_VERIFY_TOKEN` no desafio GET e `META_APP_1161210926623351_APP_SECRET` na assinatura POST.
- O token de envio `META_APP_1161210926623351_ACCESS_TOKEN` não é necessário para verificar GET/POST. O backend FastAPI de cadastro continua exigindo um token de acesso válido à WABA, digitado uma única vez na aba WhatsApp. O secret no Supabase **não fica automaticamente disponível no Render**.
- Os eventos POST só são persistidos quando `phone_number_id`, WABA `entry.id` e `meta_app_id` coincidem com o número cadastrado para o tenant. Eventos de apps diferentes jamais são repassados ao CRM legado.
- O cadastro de números passa a aceitar `meta_app_id` opcional (vazio é legado); o backend confere a identidade do app que emitiu o token por `GET /app`, valida WABA e número, e assina o app na WABA.
- Os templates, listas e a aba Disparos em massa **já existentes** são reutilizados. Este PR não libera envios reais e não altera consentimentos LGPD nem automações.

## Variáveis no **Supabase do Mugô Dados**

Preservar existentes:
`WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_FORWARD_URL`.

Confirmar presentes, sem compartilhar valores:
`META_APP_1161210926623351_APP_SECRET`,
`META_APP_1161210926623351_WEBHOOK_VERIFY_TOKEN`,
`META_APP_1161210926623351_ACCESS_TOKEN`.

## Publicação — não executar antes de validar CI e revisão

1. Aplicar migration aditiva `20270112_000121_whatsapp_meta_apps.sql` no **banco do Mugô Dados**, não no CRM.
2. Fazer merge do PR e rodar `npm run test:frontend`, `npm run typecheck` e `npm run test:backend`.
3. Publicar **somente** a Edge Function no Supabase do **Mugô Dados** (ref real do projeto, não `hdyjuyhiybjqvxsukmbn`, que é o CRM):
   `supabase functions deploy whatsapp-webhook --no-verify-jwt --project-ref <REF_SUPABASE_MUGO_DADOS>`.
4. Callback ROOVEWHATS na Meta:
   `https://<REF_SUPABASE_MUGO_DADOS>.supabase.co/functions/v1/whatsapp-webhook?meta_app_id=1161210926623351`
5. Token de verificação: valor **já cadastrado** no secret `META_APP_1161210926623351_WEBHOOK_VERIFY_TOKEN`. O endpoint devolve o `hub.challenge` apenas para token e app corretos.
6. Teste seguro: desafio GET correto → HTTP 200 com body igual ao challenge; token incorreto/sem secret → 403. Não enviar mensagens. Antes da publicação não tentar validar o callback.
7. Com webhook verificado, selecionar o tenant Roove em Relacionamento → WhatsApp → Números, registrar WABA **1491824329400600**, Phone Number ID **1063683626819387** e Meta App ID **1161210926623351**, com token autorizado do mesmo app (o backend assina a WABA). **Não tocar no número principal da Roove**.
8. Testar assinatura POST apenas com payload sintético assinado, ambiente controlado, e verificar isolamento entre empresas. O envio de templates em massa continua em modo simulado.

## Limitações e controles

- A Meta exige webhook configurado e token do mesmo aplicativo; `Inscrito` na interface não garante que a validação foi concluída.
- Se a migration não estiver aplicada, o webhook pode falhar ao consultar `meta_app_id`. Não publicar isoladamente.
- A credencial de envio do formulário é persistida na tabela `whatsapp_numbers` existente, com acesso restrito a service role; recomenda-se futura integração com cofre de segredos/cifragem em repouso própria da aplicação.
- O envio real de campanhas permanece bloqueado até evidências de opt-in por pessoa, opt-out, supressão, fila idempotente, auditoria e aprovação explícita, conforme `docs/WHATSAPP_BULK_CAMPAIGNS.md`.
- Não é possível inferir o ref do projeto Supabase do Mugô Dados a partir dos digests SHA256 dos secrets. Conferir a URL do painel antes de aplicar migration/deploy.
