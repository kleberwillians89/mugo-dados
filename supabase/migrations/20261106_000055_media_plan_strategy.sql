-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Mídia On: o plano mensal passa a guardar a estratégia escolhida.
--
-- strategy: a estratégia calculada no momento da aprovação (cenário, divisão
-- por canal, projeção, calendário semanal, limites de KPI, ações por campanha,
-- impulsionamento dos posts do calendário e a leitura da IA). Fica congelada
-- para comparar com o realizado, mesmo que os dados mudem depois.
-- scenario: qual cenário foi escolhido (ritmo_atual, meta, eficiencia,
-- personalizado).

alter table public.studio_media_plans add column if not exists strategy jsonb not null default '{}'::jsonb;
alter table public.studio_media_plans add column if not exists scenario text
  check (scenario is null or scenario in ('ritmo_atual', 'meta', 'eficiencia', 'personalizado'));
alter table public.studio_media_plans add column if not exists margin numeric(5, 4)
  check (margin is null or (margin > 0 and margin < 1));

notify pgrst, 'reload schema';
