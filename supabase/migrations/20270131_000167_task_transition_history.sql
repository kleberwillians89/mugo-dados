-- LOCAL: NAO APLICADA. Depende de 000166.
-- Movimentacoes operacionais, reaberturas e cancelamentos passam a integrar o
-- mesmo historico das aprovacoes. A tarefa nao pode mais ser apagada enquanto
-- possuir eventos auditaveis.

alter table public.studio_task_events drop constraint if exists studio_task_events_kind_check;
alter table public.studio_task_events
  add constraint studio_task_events_kind_check
  check (kind in (
    'enviado_interno', 'aprovado_interno', 'ajuste_interno', 'enviado_cliente',
    'aprovado_cliente', 'ajuste_cliente', 'comentario', 'movido_manual',
    'reaberto', 'cancelado'
  ));

alter table public.studio_task_events
  drop constraint if exists studio_task_events_task_id_fkey;
alter table public.studio_task_events
  add constraint studio_task_events_task_id_fkey
  foreign key (task_id) references public.studio_tasks(id)
  on update restrict on delete restrict;

notify pgrst, 'reload schema';
