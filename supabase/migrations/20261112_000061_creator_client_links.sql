-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Quais criadores cada empresa já consultou. A agência vê o banco inteiro;
-- o cliente vê só os criadores ligados à própria empresa (nunca a pesquisa
-- feita para outra marca).
create table if not exists public.creator_client_links (
 client_id text not null references public.clients(id) on delete cascade,
 creator_id uuid not null references public.creators(id) on delete cascade,
 created_at timestamptz not null default now(),
 primary key (client_id, creator_id)
);
alter table public.creator_client_links enable row level security;
revoke all on public.creator_client_links from anon, authenticated;
grant select on public.creator_client_links to authenticated;
grant all on public.creator_client_links to service_role;
drop policy if exists creator_client_links_member_read on public.creator_client_links;
create policy creator_client_links_member_read on public.creator_client_links for select to authenticated using (public.is_client_member(client_id));

-- Criadores já usados em shortlists passam a pertencer à empresa da shortlist.
insert into public.creator_client_links (client_id, creator_id)
select distinct client_id, creator_id from public.creator_shortlist_items
on conflict do nothing;

notify pgrst, 'reload schema';
