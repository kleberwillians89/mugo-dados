-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Arte enviada pelo próprio modal (JPG/MP4 no Storage público): carrossel com até 12 links
-- de ~150 caracteres não cabe nos 1000 de antes.
alter table public.studio_calendar_items drop constraint if exists studio_calendar_items_art_url_check;
alter table public.studio_calendar_items add constraint studio_calendar_items_art_url_check
  check (art_url is null or (art_url ~ '^https://' and length(art_url) <= 4000));
notify pgrst, 'reload schema';
