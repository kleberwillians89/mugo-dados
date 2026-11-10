-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- A criação do conteúdo passa a ser na Matriz: cada oportunidade ganha roteiro (cenas, slides ou telas)
-- e ideia de imagem (direção da arte), criados com a IA. Ao enviar ao Calendário os dois vão junto,
-- para a equipe e o cliente verem na pauta. O Calendário fica com publicação e ajustes do cliente.

alter table public.studio_matrix_opportunities add column if not exists script text
  check (script is null or length(script) <= 4000);
alter table public.studio_matrix_opportunities add column if not exists visual_idea text
  check (visual_idea is null or length(visual_idea) <= 2000);

alter table public.studio_calendar_items add column if not exists script text
  check (script is null or length(script) <= 4000);
alter table public.studio_calendar_items add column if not exists visual_idea text
  check (visual_idea is null or length(visual_idea) <= 2000);

notify pgrst, 'reload schema';
