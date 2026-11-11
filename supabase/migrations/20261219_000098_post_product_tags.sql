-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Produtos da loja (Instagram Shopping) marcados no post: publicados junto com a imagem, o carrossel ou o Reels.
-- Cada marcação: {"product_id", "name", "image_url", "slide" (0 = primeira arte), "x", "y" (0.01 a 1, só imagem)}.
alter table public.studio_calendar_items add column if not exists product_tags jsonb not null default '[]'::jsonb;
alter table public.studio_calendar_items drop constraint if exists studio_calendar_items_product_tags_check;
alter table public.studio_calendar_items add constraint studio_calendar_items_product_tags_check
  check (jsonb_typeof(product_tags) = 'array' and jsonb_array_length(product_tags) <= 30);

notify pgrst, 'reload schema';
