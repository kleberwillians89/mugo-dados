-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Referências da marca: links e artes que o cliente gosta (Aprovação → Referências).
-- Cliente e equipe Mugô adicionam; a IA de conteúdo e a equipe usam como norte visual.
create table if not exists public.studio_references (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  url text not null check (url ~ '^https://' and length(url) <= 2000),
  kind text not null default 'link' check (kind in ('link', 'arte')),
  note text check (note is null or length(note) <= 500),
  author_id uuid,
  author_side text not null check (author_side in ('cliente', 'mugo')),
  created_at timestamptz not null default now()
);
create index if not exists studio_references_client_idx on public.studio_references (client_id, created_at desc);
alter table public.studio_references enable row level security;
revoke all on public.studio_references from anon, authenticated;
grant all on public.studio_references to service_role;

notify pgrst, 'reload schema';
