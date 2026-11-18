-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Opções de publicação do Reels no Instagram, escolhidas no modal do post (formato Reels):
-- {"cover_mode": "frame"|"image", "thumb_offset_ms": 0..900000, "cover_url": "https://…jpg",
--  "share_to_feed": true|false, "trial": "off"|"manual"|"auto", "audio_name": "…", "first_comment": "…"}
-- Vazio ({}) = comportamento de antes: capa no primeiro frame, Reels também no Feed, sem teste.
alter table public.studio_calendar_items add column if not exists reels_options jsonb not null default '{}'::jsonb;
alter table public.studio_calendar_items drop constraint if exists studio_calendar_items_reels_options_check;
alter table public.studio_calendar_items add constraint studio_calendar_items_reels_options_check
  check (jsonb_typeof(reels_options) = 'object' and pg_column_size(reels_options) <= 8192);

notify pgrst, 'reload schema';
