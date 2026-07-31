# Administrador global e cadastro de empresas

## Aplicação da migration

Revise primeiro o projeto vinculado e o plano, sem aplicar:

```bash
supabase projects list
supabase migration list --linked
supabase db push --linked --dry-run
```

O dry-run deve terminar em:

```text
20260801_000020_platform_admin_companies.sql
```

Depois da revisão explícita, aplique:

```bash
supabase db push --linked
```

Não use `migration repair`: a migration 020 é nova e não altera o histórico remoto.

## Backend

Configure `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` e
`SUPABASE_INVITE_REDIRECT_URL`. A service role deve existir somente no backend.

`SUPABASE_INVITE_REDIRECT_URL` deve apontar para a URL pública em que o usuário
convidado concluirá o login/onboarding e também precisa estar liberada nas Redirect
URLs do Supabase Auth.

## Primeiro acesso

1. Confirme no Supabase Auth que o UID de `mugo.agencia@gmail.com` é
   `ad1a0f59-7984-40af-a46a-f4a998983000`.
2. Aplique a migration 020.
3. Inicie backend e frontend com as variáveis corretas.
4. Entre com o usuário mestre.
5. Abra `/empresas`; o usuário não precisa de `client_memberships`.
6. Cadastre uma empresa de teste e confirme o recebimento do convite do owner.
7. Aceite o convite e confirme que a empresa muda de `invitation_pending` para
   `active`.
8. Use “Abrir para suporte” e confirme que o dashboard abre somente o tenant
   escolhido.

## Segurança

O papel vem de `public.platform_admins`, não de e-mail nem de metadata do JWT.
Usuários autenticados podem ler apenas a própria linha e não possuem política de
insert/update/delete. Criação, compensação e auditoria são RPCs exclusivas da
`service_role`, e cada RPC também valida o ator na tabela de administradores.
