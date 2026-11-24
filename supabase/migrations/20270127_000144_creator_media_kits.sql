-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Mídia kit e valores de cada criador, por empresa: arquivos (PDF/imagem ou link),
-- tabela de preços por entregável, e-mail, telefone, contato e observações, e o histórico
-- de fechamentos (cada "Fechado" guarda valor, o que foi fechado, data e observação). Os valores negociados
-- são da empresa: o cliente vê só os da própria marca; a agência vê todos.
-- Nenhuma escrita pelo browser: tudo passa pelo backend (service_role).

create table if not exists public.creator_media_kits (
 id uuid primary key default gen_random_uuid(),
 client_id text not null references public.clients(id) on delete cascade,
 creator_id uuid not null references public.creators(id) on delete cascade,
 files jsonb not null default '[]'::jsonb,
 prices jsonb not null default '[]'::jsonb,
 email text check (email is null or length(email) <= 200),
 phone text check (phone is null or length(phone) <= 40),
 contact text check (contact is null or length(contact) <= 300),
 deals jsonb not null default '[]'::jsonb,
 notes text check (notes is null or length(notes) <= 4000),
 updated_by text,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique (client_id, creator_id)
);
create index if not exists creator_media_kits_client_idx on public.creator_media_kits(client_id, updated_at desc);

alter table public.creator_media_kits enable row level security;
revoke all on public.creator_media_kits from anon, authenticated;
grant select on public.creator_media_kits to authenticated;
grant all on public.creator_media_kits to service_role;
drop policy if exists creator_media_kits_member_read on public.creator_media_kits;
create policy creator_media_kits_member_read on public.creator_media_kits for select to authenticated using (public.is_client_member(client_id));

notify pgrst, 'reload schema';
