alter table public.ig_comments
  add column if not exists theme_ai text,
  add column if not exists theme_reviewed boolean not null default false;

alter table public.ig_dm_messages
  add column if not exists theme_ai text,
  add column if not exists theme_reviewed boolean not null default false;

notify pgrst, 'reload schema';
