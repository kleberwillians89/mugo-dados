-- Somente leitura. Resultado vazio em todas as consultas e requisito para 000165.

-- Tarefas ausentes ou pertencentes a outro tenant.
select
  link.id as link_id,
  link.client_id as link_client_id,
  link.task_id,
  task.client_id as task_client_id,
  case when task.id is null then 'missing_task' else 'task_tenant_mismatch' end as issue
from public.task_work_links as link
left join public.studio_tasks as task on task.id = link.task_id
where task.id is null or task.client_id is distinct from link.client_id
order by link.created_at, link.id;

-- Briefings ausentes ou pertencentes a outro tenant.
select
  link.id as link_id,
  link.client_id as link_client_id,
  link.brief_id,
  brief.client_id as brief_client_id,
  case when brief.id is null then 'missing_brief' else 'brief_tenant_mismatch' end as issue
from public.task_work_links as link
left join public.studio_briefs as brief on brief.id = link.brief_id
where link.brief_id is not null
  and (brief.id is null or brief.client_id is distinct from link.client_id)
order by link.created_at, link.id;

-- Chaves compostas que impediriam a criacao dos constraints unicos.
select client_id, id, count(*) as duplicate_count
from public.studio_tasks
group by client_id, id
having count(*) > 1;

select client_id, id, count(*) as duplicate_count
from public.studio_briefs
group by client_id, id
having count(*) > 1;
