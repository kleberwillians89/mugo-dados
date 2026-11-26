-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva (reversão no fim do arquivo).
-- Perfil "Cliente — Aprovação Final" (preset cliente_aprovacao): o cliente entra direto na Aprovação Final e só
-- revisa, aprova, pede ajuste e comenta. Os códigos final_approval.view/.edit já cabem na regra atual
-- de client_member_permissions; aqui só o preset novo entra na lista permitida. Ninguém muda de perfil sozinho.
alter table public.client_memberships drop constraint if exists client_memberships_preset_check;
alter table public.client_memberships add constraint client_memberships_preset_check
  check (permission_preset is null or permission_preset in
    ('administrador', 'gestor', 'marketing', 'comercial', 'visualizacao', 'personalizado', 'cliente_aprovacao'));
notify pgrst, 'reload schema';

-- Reversão (antes, volte quem estiver em cliente_aprovacao para outro perfil):
-- alter table public.client_memberships drop constraint if exists client_memberships_preset_check;
-- alter table public.client_memberships add constraint client_memberships_preset_check
--   check (permission_preset is null or permission_preset in
--     ('administrador', 'gestor', 'marketing', 'comercial', 'visualizacao', 'personalizado'));
