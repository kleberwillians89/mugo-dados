alter table public.studio_projects
    add column if not exists research jsonb;
