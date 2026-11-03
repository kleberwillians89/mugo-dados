-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- 000071 (era 000070; renumerada porque a main ganhou 000070_social_reports). Status de entrega da Meta (enviado → entregue → lido) nas mensagens do Studio (aprovação, resumos),
-- repassado pelo webhook do CRM (/api/hooks/crm, type=message_status).
alter table public.studio_messages
  add column if not exists delivery_status text check (delivery_status is null or delivery_status in ('accepted', 'sent', 'delivered', 'read', 'failed')),
  add column if not exists delivery_updated_at timestamptz,
  add column if not exists delivery_error text check (delivery_error is null or length(delivery_error) <= 300);
create index if not exists studio_messages_provider_idx on public.studio_messages (provider_message_id) where provider_message_id is not null;
notify pgrst, 'reload schema';
