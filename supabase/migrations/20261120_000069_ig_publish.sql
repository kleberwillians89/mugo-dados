-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- 1) IA dos comentários desligada por padrão até o cliente validar (se a 000068 já rodou com "true").
-- 2) Publicação no Instagram (Content Publishing API) dos posts aprovados e com agendamento validado.
alter table public.ig_engagement_settings alter column ai_autoreply set default false;

alter table public.studio_calendar_items
  add column if not exists publish_status text check (publish_status is null or publish_status in ('publicando', 'publicado', 'falhou', 'simulado', 'manual')),
  add column if not exists publish_error text check (publish_error is null or length(publish_error) <= 300),
  add column if not exists published_media_id text,
  add column if not exists published_permalink text;
create index if not exists studio_calendar_items_publish_due_idx
  on public.studio_calendar_items (scheduled_at) where status = 'aprovado' and schedule_confirmed_at is not null and publish_status is null;

notify pgrst, 'reload schema';
