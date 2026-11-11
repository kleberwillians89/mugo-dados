-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Briefing da peça na Matriz (campos do Atendimento do iAgência): nasce junto com o conteúdo da oportunidade
-- e vai para a pauta do Calendário na exportação (signals.briefing).
alter table public.studio_matrix_opportunities add column if not exists briefing jsonb not null default '{}'::jsonb;
alter table public.studio_matrix_opportunities drop constraint if exists studio_matrix_opportunities_briefing_check;
alter table public.studio_matrix_opportunities add constraint studio_matrix_opportunities_briefing_check check (jsonb_typeof(briefing) = 'object');

notify pgrst, 'reload schema';
