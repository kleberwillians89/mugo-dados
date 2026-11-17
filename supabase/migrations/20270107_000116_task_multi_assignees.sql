-- Multi-assignee tasks. Keeps legacy primary assignee fields intact.
-- Existing cards and API consumers continue to work unchanged.
ALTER TABLE public.studio_tasks
  ADD COLUMN IF NOT EXISTS assignee_user_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
  ADD COLUMN IF NOT EXISTS assignee_names text[] NOT NULL DEFAULT '{}'::text[];

UPDATE public.studio_tasks
SET assignee_user_ids = ARRAY[assignee_user_id],
    assignee_names = ARRAY[COALESCE(NULLIF(btrim(assignee_name), ''), 'Responsável')]
WHERE assignee_user_id IS NOT NULL AND cardinality(assignee_user_ids) = 0;

CREATE INDEX IF NOT EXISTS studio_tasks_assignee_user_ids_idx
  ON public.studio_tasks USING GIN (assignee_user_ids);

COMMENT ON COLUMN public.studio_tasks.assignee_user_ids IS
  'Membros responsáveis desta tarefa, sempre limitados aos membros ativos do tenant.';
COMMENT ON COLUMN public.studio_tasks.assignee_names IS
  'Nomes de exibição associados, na mesma ordem de assignee_user_ids.';
