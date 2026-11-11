-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva (depois da 000096).
-- Calendário e Tarefas no mesmo fluxo: ajuste pedido num post (pelo cliente ou pela revisão interna)
-- vira tarefa em "Ajustes", ligada ao post; a tarefa acompanha o post (em revisão, com o cliente,
-- aprovado/publicado = concluída). Um post tem no máximo uma tarefa ligada por empresa.

alter table public.studio_tasks
  add column if not exists calendar_item_id uuid references public.studio_calendar_items(id) on delete set null;
create unique index if not exists studio_tasks_calendar_item_uq
  on public.studio_tasks (client_id, calendar_item_id) where calendar_item_id is not null;

notify pgrst, 'reload schema';
