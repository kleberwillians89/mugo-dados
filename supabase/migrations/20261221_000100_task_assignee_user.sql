-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Responsável da tarefa passa a ser um usuário da empresa (não só um nome digitado): quem não é admin vê só
-- as tarefas dele (responsável ou quem criou). Usado também pelo "Enviar briefing para" (designer, tráfego…).
alter table public.studio_tasks add column if not exists assignee_user_id uuid;
create index if not exists studio_tasks_assignee_idx on public.studio_tasks (client_id, assignee_user_id) where assignee_user_id is not null;
create index if not exists studio_tasks_created_by_idx on public.studio_tasks (client_id, created_by);

notify pgrst, 'reload schema';
