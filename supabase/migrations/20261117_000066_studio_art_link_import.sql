-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Link da arte (Canva/Google Drive) em cada post e importação de calendários prontos (PowerPoint).
-- art_url: só https, até 1000 caracteres. origin ganha 'importado' (post que veio de um calendário
-- já aprovado fora da plataforma; reviewed_by fica 'importado:<usuário>').
alter table public.studio_calendar_items add column if not exists art_url text;
alter table public.studio_calendar_items drop constraint if exists studio_calendar_items_art_url_check;
alter table public.studio_calendar_items add constraint studio_calendar_items_art_url_check
  check (art_url is null or (art_url ~ '^https://' and length(art_url) <= 1000));

alter table public.studio_calendar_items drop constraint if exists studio_calendar_items_origin_check;
alter table public.studio_calendar_items add constraint studio_calendar_items_origin_check
  check (origin in ('ia', 'manual', 'importado'));
