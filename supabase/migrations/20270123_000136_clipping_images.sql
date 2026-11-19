-- Clipping em cards: imagem da matéria (og:image / mídia do feed) e domínio do veículo (para o ícone).
alter table public.studio_clippings
  add column if not exists image_url text check (image_url is null or (image_url ~ '^https://' and length(image_url) <= 1000)),
  add column if not exists source_domain text check (source_domain is null or length(source_domain) <= 200);
alter table public.news_articles
  add column if not exists image_url text check (image_url is null or (image_url ~ '^https://' and length(image_url) <= 1000));

notify pgrst, 'reload schema';
