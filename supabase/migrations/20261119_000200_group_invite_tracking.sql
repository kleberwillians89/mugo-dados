-- Migration aditiva: links de convite rastreáveis por tenant e por jornada.
-- NÃO executar automaticamente em produção; requer homologação e revisão RLS.
create table if not exists public.relationship_group_invite_links (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  campaign_key text not null check (campaign_key ~ '^[a-z0-9_-]{2,80}$'),
  label text not null check (char_length(label) between 2 and 100),
  variant text not null check (variant in ('direct', 'post_signup')),
  slug text not null unique check (slug ~ '^[a-zA-Z0-9_-]{22,90}$'),
  invite_url text not null check (invite_url ~ '^https://chat[.]whatsapp[.]com/[A-Za-z0-9]+([?][^#]*)?$'),
  active boolean not null default true,
  click_count bigint not null default 0 check (click_count >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, campaign_key, variant)
);
create index if not exists group_invite_links_tenant_campaign
  on public.relationship_group_invite_links(client_id, campaign_key);
alter table public.relationship_group_invite_links enable row level security;
revoke all on public.relationship_group_invite_links from anon, authenticated;
-- Apenas service_role acessa tabela. A autorização passa pela API, que resolve o tenant.
grant select, insert, update on public.relationship_group_invite_links to service_role;

create or replace function public.register_group_invite_click(p_slug text)
returns table (destination_url text, campaign text, link_variant text)
language plpgsql security definer set search_path = public
as $$
begin
  return query
  update public.relationship_group_invite_links l
     set click_count = l.click_count + 1,
         updated_at = now()
   where l.slug = p_slug and l.active = true
   returning l.invite_url, l.campaign_key, l.variant;
end;
$$;
revoke all on function public.register_group_invite_click(text) from public, anon, authenticated;
grant execute on function public.register_group_invite_click(text) to service_role;
