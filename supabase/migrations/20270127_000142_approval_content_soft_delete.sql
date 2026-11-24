-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Exclusão lógica das filas de aprovação. O conteúdo permanece no banco para preservar
-- histórico, comentários, decisões e vínculos; leituras operacionais ignoram deleted_at.

alter table public.studio_calendar_items
  add column if not exists deleted_at timestamptz,
  add column if not exists deleted_by text;

create index if not exists studio_calendar_items_active_month_idx
  on public.studio_calendar_items (client_id, month, scheduled_at)
  where deleted_at is null;

notify pgrst, 'reload schema';
