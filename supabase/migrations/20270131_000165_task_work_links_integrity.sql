-- LOCAL: NAO APLICADA. Migration aditiva; validar primeiro com o preflight 000165.
-- task_work_links deve apontar para tarefa/briefing do mesmo tenant sem apagar
-- rastreabilidade quando o registro de origem ainda estiver referenciado.

alter table public.studio_tasks
  add constraint studio_tasks_client_id_id_key unique (client_id, id);

alter table public.studio_briefs
  add constraint studio_briefs_client_id_id_key unique (client_id, id);

alter table public.task_work_links
  add constraint task_work_links_task_same_tenant_fk
  foreign key (client_id, task_id)
  references public.studio_tasks (client_id, id)
  on update restrict
  on delete restrict
  not valid;

alter table public.task_work_links
  add constraint task_work_links_brief_same_tenant_fk
  foreign key (client_id, brief_id)
  references public.studio_briefs (client_id, id)
  on update restrict
  on delete restrict
  not valid;

alter table public.task_work_links
  validate constraint task_work_links_task_same_tenant_fk;

alter table public.task_work_links
  validate constraint task_work_links_brief_same_tenant_fk;

notify pgrst, 'reload schema';

-- Reversao (manual, sem remover dados):
-- alter table public.task_work_links drop constraint if exists task_work_links_brief_same_tenant_fk;
-- alter table public.task_work_links drop constraint if exists task_work_links_task_same_tenant_fk;
-- alter table public.studio_briefs drop constraint if exists studio_briefs_client_id_id_key;
-- alter table public.studio_tasks drop constraint if exists studio_tasks_client_id_id_key;
