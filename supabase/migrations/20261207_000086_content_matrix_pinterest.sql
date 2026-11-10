-- LOCAL: NÃO APLICADA. Compatibilidade do planejamento editorial com Pinterest.
-- Mantém o bucket, RLS, publicação e integrações inalterados: Pinterest continua publicação manual.

alter table public.studio_calendar_items drop constraint if exists studio_calendar_items_channel_check;
alter table public.studio_calendar_items add constraint studio_calendar_items_channel_check
  check (channel in ('instagram', 'facebook', 'tiktok', 'linkedin', 'youtube', 'pinterest'));

alter table public.studio_matrix_opportunities drop constraint if exists studio_matrix_opportunities_platform_check;
alter table public.studio_matrix_opportunities add constraint studio_matrix_opportunities_platform_check
  check (platform in ('instagram', 'facebook', 'tiktok', 'linkedin', 'youtube', 'pinterest'));

notify pgrst, 'reload schema';
