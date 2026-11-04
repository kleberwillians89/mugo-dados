-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Referência também pode ser de UM post (modal do post → "Referências deste post").
alter table public.studio_references
  add column if not exists item_id uuid references public.studio_calendar_items(id) on delete cascade;
create index if not exists studio_references_item_idx on public.studio_references (client_id, item_id) where item_id is not null;

notify pgrst, 'reload schema';
