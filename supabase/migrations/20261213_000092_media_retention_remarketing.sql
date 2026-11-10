-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Mídia On ganha os objetivos Retenção de clientes e Remarketing (além de vendas, leads, tráfego e alcance),
-- e passa a gerar sozinho, no começo de cada mês, uma estratégia por objetivo para cada empresa.

alter table public.studio_media_plans drop constraint if exists studio_media_plans_objective_check;
alter table public.studio_media_plans add constraint studio_media_plans_objective_check
  check (objective in ('vendas', 'leads', 'trafego', 'alcance', 'retencao', 'remarketing'));

alter table public.studio_media_strategies drop constraint if exists studio_media_strategies_objective_check;
alter table public.studio_media_strategies add constraint studio_media_strategies_objective_check
  check (objective in ('vendas', 'leads', 'trafego', 'alcance', 'retencao', 'remarketing'));

notify pgrst, 'reload schema';
