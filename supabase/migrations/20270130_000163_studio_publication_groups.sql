alter table public.studio_calendar_items add column publication_group_id uuid;
create unique index studio_publication_destination_unique
  on public.studio_calendar_items(client_id, publication_group_id, channel)
  where publication_group_id is not null;

create function public.create_studio_publication_group(p_client_id text, p_rows jsonb)
returns setof public.studio_calendar_items
language plpgsql set search_path = '' as $$
declare
  entry jsonb;
  candidate public.studio_calendar_items;
begin
  for entry in select value from jsonb_array_elements(p_rows) loop
    select * into candidate from jsonb_populate_record(null::public.studio_calendar_items, entry);
    insert into public.studio_calendar_items (
      client_id, publication_group_id, month, scheduled_at, channel, format, pillar,
      title, hook, caption_draft, rationale, status, origin, created_by, art_url,
      collaborators, product_tags, reels_options, creative_direction
    ) values (
      p_client_id, candidate.publication_group_id, candidate.month, candidate.scheduled_at, candidate.channel,
      candidate.format, candidate.pillar, candidate.title, candidate.hook, candidate.caption_draft, candidate.rationale,
      'rascunho', 'manual', candidate.created_by, candidate.art_url, coalesce(candidate.collaborators, '{}'::text[]),
      coalesce(candidate.product_tags, '[]'::jsonb), coalesce(candidate.reels_options, '{}'::jsonb),
      coalesce(candidate.creative_direction, '{}'::jsonb)
    ) on conflict (client_id, publication_group_id, channel) where publication_group_id is not null do nothing;
    return query select i.* from public.studio_calendar_items i where i.client_id = p_client_id
      and i.publication_group_id = candidate.publication_group_id and i.channel = candidate.channel;
  end loop;
end;
$$;
revoke all on function public.create_studio_publication_group(text,jsonb) from public, anon, authenticated;
grant execute on function public.create_studio_publication_group(text,jsonb) to service_role;
notify pgrst, 'reload schema';
